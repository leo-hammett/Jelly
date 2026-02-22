"""Thin utilities for installing and talking to MCP servers.

Policy:
- stdio transport is supported for Python-native MCP servers.
- Node-family servers (npx/node/npm/etc.) are intentionally blocked on stdio in this
  module due known reliability issues on macOS. Use an HTTP/SSE sidecar path instead.
"""

from __future__ import annotations

import json
import os
import select
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jelly.config import Config
from jelly.run_logging import RunLogger

_next_id = 0
_NODE_STDIO_COMMANDS = {
    "node",
    "npx",
    "npm",
    "pnpm",
    "yarn",
    "bun",
}


@dataclass
class MCPServer:
    """Everything needed to start and talk to one MCP server."""

    name: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    install_cmd: str | list[str] | None = None
    transport: str = "stdio"  # "stdio" | "http_sse"
    endpoint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Dynamic sidecar provisioning fields for unresolved HTTP servers.
    dynamic_sidecar: bool = False
    sidecar_package: str | None = None
    sidecar_command: list[str] = field(default_factory=list)
    sidecar_port: int | None = None


@dataclass
class MCPTestStep:
    """A single test action to replay against an MCP server."""

    description: str
    server: str
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    expected: str = ""


@dataclass
class MCPTestPlan:
    """A full MCP-based test plan: which servers to run, what steps to execute."""

    servers: list[MCPServer] = field(default_factory=list)
    steps: list[MCPTestStep] = field(default_factory=list)
    reason: str = ""


@dataclass
class MCPBootstrapResult:
    """Result of deterministic startup MCP bootstrap."""

    requested_servers: list[str] = field(default_factory=list)
    available_servers: list[MCPServer] = field(default_factory=list)
    unavailable: dict[str, str] = field(default_factory=dict)

    def to_status(self) -> dict[str, Any]:
        return {
            "requested_servers": self.requested_servers,
            "available_servers": [s.name for s in self.available_servers],
            "available_count": len(self.available_servers),
            "unavailable": dict(self.unavailable),
            "unavailable_count": len(self.unavailable),
        }


def bootstrap_servers(
    config: Config,
    project_dir: str,
    logger: RunLogger | None = None,
) -> MCPBootstrapResult:
    """Install and validate a deterministic MCP preset for the current run."""
    if not config.mcp_bootstrap_enabled:
        _log(logger, "INFO", "bootstrap.skipped", reason="disabled")
        return MCPBootstrapResult()

    servers = build_bootstrap_servers(config, project_dir)
    result = MCPBootstrapResult(requested_servers=[s.name for s in servers])
    for server in servers:
        if server.install_cmd:
            installed = install_server(server, logger=logger)
            if not installed:
                result.unavailable[server.name] = "install_failed"
                _log(
                    logger,
                    "WARNING",
                    "bootstrap.server_unavailable",
                    server=server.name,
                    reason="install_failed",
                )
                continue

        available, reason = _check_server_availability(server)
        if available:
            result.available_servers.append(server)
            _log(
                logger,
                "INFO",
                "bootstrap.server_available",
                server=server.name,
                transport=server.transport,
            )
        else:
            result.unavailable[server.name] = reason
            _log(
                logger,
                "WARNING",
                "bootstrap.server_unavailable",
                server=server.name,
                reason=reason,
                transport=server.transport,
            )
    _log(logger, "INFO", "bootstrap.complete", **result.to_status())
    return result


def build_bootstrap_servers(config: Config, project_dir: str) -> list[MCPServer]:
    """Build deterministic MCP presets based on transport policy."""
    preset = config.mcp_bootstrap_preset.strip().lower()
    if preset != "filesystem_browser":
        return []

    transport_mode = config.mcp_transport_mode.strip().lower()
    filesystem_workspace = str((Path(project_dir) / ".mcp" / "filesystem").resolve())
    fs_install = (
        ["npm", "install", "-g", "@modelcontextprotocol/server-filesystem"]
        if config.mcp_bootstrap_install
        else None
    )
    browser_install = (
        ["npm", "install", "-g", "@playwright/mcp"]
        if config.mcp_bootstrap_install
        else None
    )

    if transport_mode == "python_stdio_only":
        # No in-repo Python MCP sidecars are bundled yet.
        return []

    if transport_mode == "allow_node_stdio":
        return [
            MCPServer(
                name="filesystem",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", filesystem_workspace],
                install_cmd=fs_install,
                transport="stdio",
                metadata={"node_stdio": True},
            ),
            MCPServer(
                name="browser",
                command="npx",
                args=["-y", "@playwright/mcp"],
                install_cmd=browser_install,
                transport="stdio",
                metadata={"node_stdio": True},
            ),
        ]

    # Default: Node sidecars over HTTP/SSE endpoints.
    fs_endpoint = os.getenv(config.mcp_filesystem_endpoint_env, "").strip() or None
    browser_endpoint = os.getenv(config.mcp_browser_endpoint_env, "").strip() or None
    return [
        MCPServer(
            name="filesystem",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", filesystem_workspace],
            install_cmd=fs_install,
            transport="http_sse",
            endpoint=fs_endpoint,
            dynamic_sidecar=False,
            metadata={"endpoint_env": config.mcp_filesystem_endpoint_env},
        ),
        MCPServer(
            name="browser",
            command="npx",
            args=["-y", "@playwright/mcp"],
            install_cmd=browser_install,
            transport="http_sse",
            endpoint=browser_endpoint,
            dynamic_sidecar=False,
            metadata={"endpoint_env": config.mcp_browser_endpoint_env},
        ),
    ]


def can_lazy_provision(server: MCPServer) -> bool:
    """Whether a server should be provisioned dynamically at runtime."""
    return (
        server.transport == "http_sse"
        and server.dynamic_sidecar
        and not (server.endpoint or "").strip()
    )


def sidecar_launch_command(server: MCPServer) -> list[str]:
    """Resolve the stdio command used behind the HTTP sidecar bridge."""
    if server.sidecar_command:
        return [str(part) for part in server.sidecar_command if str(part).strip()]
    if server.command:
        return [server.command, *server.args]
    if server.sidecar_package:
        return ["npx", "-y", server.sidecar_package]
    raise RuntimeError(
        f"Dynamic sidecar '{server.name}' is missing sidecar command/package metadata."
    )


def sidecar_install_command(server: MCPServer) -> list[str] | None:
    """Resolve install command for dynamic sidecars."""
    if server.install_cmd:
        normalized = _normalize_install_cmd(server.install_cmd)
        return normalized or None
    if server.sidecar_package:
        return ["npm", "install", "-g", server.sidecar_package]
    return None


def install_server(
    server: MCPServer,
    timeout: int = 120,
    logger: RunLogger | None = None,
) -> bool:
    """Install an MCP server using its install_cmd (npm, pip, etc.).

    Returns True if install succeeded or no install_cmd was needed.
    """
    if not server.install_cmd:
        _log(logger, "DEBUG", "install_server.skipped", server=server.name)
        return True

    install_cmd = _normalize_install_cmd(server.install_cmd)
    if not install_cmd:
        _log(
            logger,
            "ERROR",
            "install_server.invalid_command",
            server=server.name,
            install_cmd=server.install_cmd,
        )
        return False

    _log(
        logger,
        "INFO",
        "install_server.start",
        server=server.name,
        install_cmd=install_cmd,
        timeout_seconds=timeout,
    )
    try:
        result = subprocess.run(
            install_cmd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        ok = result.returncode == 0
        _log(
            logger,
            "INFO" if ok else "ERROR",
            "install_server.complete",
            server=server.name,
            returncode=result.returncode,
            stdout_tail=result.stdout[-500:],
            stderr_tail=result.stderr[-500:],
        )
        return ok
    except (subprocess.TimeoutExpired, OSError) as exc:
        _log(
            logger,
            "ERROR",
            "install_server.exception",
            server=server.name,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return False


def start_server(
    server: MCPServer,
    startup_wait: float = 3.0,
    request_timeout: float = 30.0,
    logger: RunLogger | None = None,
    allow_node_stdio: bool = False,
) -> subprocess.Popen:
    """Start an MCP server subprocess. Returns the Popen handle.

    Waits for the process to be ready, then sends the JSON-RPC
    `initialize` handshake before returning.
    """
    _assert_stdio_server_allowed(server, logger, allow_node_stdio=allow_node_stdio)
    _preflight_server(server, logger)
    env = {**os.environ, **server.env}
    proc = subprocess.Popen(
        [server.command, *server.args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        env=env,
    )
    _log(
        logger,
        "INFO",
        "start_server.spawned",
        server=server.name,
        command=server.command,
        args=server.args,
    )
    try:
        # Respect caller-provided startup_wait so slower Python servers can warm up.
        deadline = time.monotonic() + max(0.0, startup_wait)
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                stderr_tail = _stderr_tail(proc)
                raise RuntimeError(
                    f"MCP server '{server.name}' exited during startup "
                    f"(code {proc.returncode}). {stderr_tail}"
                )
            time.sleep(0.1)

        _send_jsonrpc(
            proc,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "jelly", "version": "1.0"},
            },
            timeout=request_timeout,
            logger=logger,
            server_name=server.name,
        )
        _send_notification(
            proc,
            "notifications/initialized",
            logger=logger,
            server_name=server.name,
        )
    except Exception as exc:
        stderr_tail = _stderr_tail(proc)
        try:
            stop_server(proc)
        except Exception:
            pass
        raise RuntimeError(
            f"Failed to start MCP server '{server.name}' "
            f"({server.command} {' '.join(server.args)}): {exc}. "
            f"stderr: {stderr_tail}"
        ) from exc

    _log(logger, "INFO", "start_server.ready", server=server.name)
    return proc


def call_tool(
    proc: subprocess.Popen,
    tool_name: str,
    arguments: dict[str, Any],
    timeout: float = 30.0,
    logger: RunLogger | None = None,
    server_name: str | None = None,
) -> dict[str, Any]:
    """Send a tools/call JSON-RPC request and return the result."""
    response = _send_jsonrpc(
        proc,
        "tools/call",
        {
            "name": tool_name,
            "arguments": arguments,
        },
        timeout=timeout,
        logger=logger,
        server_name=server_name,
    )
    if "error" in response:
        raise RuntimeError(f"MCP tool error: {response['error']}")
    return response.get("result", {})


def start_server_for_transport(
    server: MCPServer,
    startup_wait: float = 3.0,
    request_timeout: float = 30.0,
    logger: RunLogger | None = None,
    allow_node_stdio: bool = False,
) -> subprocess.Popen | None:
    """Start or validate a server based on transport.

    For stdio, returns a subprocess handle. For HTTP/SSE, validates connectivity
    and returns None.
    """
    if server.transport == "http_sse":
        endpoint = (server.endpoint or "").strip()
        if not endpoint:
            env_name = server.metadata.get("endpoint_env", "endpoint")
            raise RuntimeError(
                f"MCP server '{server.name}' has no HTTP/SSE endpoint configured "
                f"(set {env_name})."
            )
        _send_jsonrpc_http(
            endpoint,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "jelly", "version": "1.0"},
            },
            timeout=request_timeout,
            logger=logger,
            server_name=server.name,
        )
        return None

    return start_server(
        server,
        startup_wait=startup_wait,
        request_timeout=request_timeout,
        logger=logger,
        allow_node_stdio=allow_node_stdio,
    )


def call_tool_for_server(
    server: MCPServer,
    proc: subprocess.Popen | None,
    tool_name: str,
    arguments: dict[str, Any],
    timeout: float = 30.0,
    logger: RunLogger | None = None,
) -> dict[str, Any]:
    """Call a server tool across stdio or HTTP/SSE transports."""
    if server.transport == "http_sse":
        endpoint = (server.endpoint or "").strip()
        if not endpoint:
            raise RuntimeError(
                f"MCP server '{server.name}' has no HTTP/SSE endpoint configured."
            )
        response = _send_jsonrpc_http(
            endpoint,
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            timeout=timeout,
            logger=logger,
            server_name=server.name,
        )
        if "error" in response:
            raise RuntimeError(f"MCP tool error: {response['error']}")
        return response.get("result", {})

    if proc is None:
        raise RuntimeError(f"Server process is unavailable for '{server.name}'")
    return call_tool(
        proc,
        tool_name,
        arguments,
        timeout=timeout,
        logger=logger,
        server_name=server.name,
    )


def stop_server(proc: subprocess.Popen) -> None:
    """Gracefully shut down an MCP server subprocess."""
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def stop_server_for_transport(server: MCPServer, proc: subprocess.Popen | None) -> None:
    """Stop only transports that require owned subprocess handles."""
    if server.transport == "http_sse":
        return
    if proc is not None:
        stop_server(proc)


def _send_notification(
    proc: subprocess.Popen,
    method: str,
    params: dict | None = None,
    logger: RunLogger | None = None,
    server_name: str | None = None,
) -> None:
    """Send a JSON-RPC 2.0 notification (no id, no response expected)."""
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    _write_message(proc, msg)
    _log(
        logger,
        "DEBUG",
        "notification.sent",
        server=server_name,
        method=method,
    )


def _send_jsonrpc(
    proc: subprocess.Popen,
    method: str,
    params: dict,
    timeout: float = 30.0,
    logger: RunLogger | None = None,
    server_name: str | None = None,
) -> dict:
    """Write a JSON-RPC 2.0 request to the process's stdin, read the response."""
    global _next_id
    _next_id += 1
    msg_id = _next_id

    request: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": method,
        "params": params,
    }
    _write_message(proc, request)
    _log(
        logger,
        "DEBUG",
        "jsonrpc.sent",
        server=server_name,
        method=method,
        msg_id=msg_id,
    )

    deadline = time.monotonic() + timeout
    while True:
        remaining = max(0.0, deadline - time.monotonic())
        if remaining == 0:
            raise TimeoutError(
                f"MCP server did not respond to '{method}' (server={server_name})"
            )
        message = _read_message(proc, remaining)
        try:
            response = message if isinstance(message, dict) else json.loads(message)
        except json.JSONDecodeError:
            _log(
                logger,
                "WARNING",
                "jsonrpc.decode_error",
                server=server_name,
                method=method,
                msg_id=msg_id,
            )
            continue
        if response.get("id") == msg_id:
            _log(
                logger,
                "DEBUG",
                "jsonrpc.received",
                server=server_name,
                method=method,
                msg_id=msg_id,
            )
            return response
        _log(
            logger,
            "DEBUG",
            "jsonrpc.ignored_message",
            server=server_name,
            method=method,
            msg_id=msg_id,
            received_id=response.get("id"),
            received_method=response.get("method"),
        )


def _send_jsonrpc_http(
    endpoint: str,
    method: str,
    params: dict[str, Any],
    timeout: float = 30.0,
    logger: RunLogger | None = None,
    server_name: str | None = None,
) -> dict[str, Any]:
    """Send a JSON-RPC request to an HTTP/SSE sidecar endpoint."""
    global _next_id
    _next_id += 1
    msg_id = _next_id
    request_payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": method,
        "params": params,
    }
    body = json.dumps(request_payload, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    req = Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    _log(
        logger,
        "DEBUG",
        "jsonrpc_http.sent",
        server=server_name,
        endpoint=endpoint,
        method=method,
        msg_id=msg_id,
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except HTTPError as exc:
        raise RuntimeError(
            f"HTTP {exc.code} from MCP endpoint {endpoint} during '{method}'"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Unable to reach MCP endpoint {endpoint} during '{method}': {exc.reason}"
        ) from exc

    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid JSON response from MCP endpoint {endpoint} during '{method}'"
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Unexpected MCP endpoint response shape for '{method}': {type(payload).__name__}"
        )
    _log(
        logger,
        "DEBUG",
        "jsonrpc_http.received",
        server=server_name,
        endpoint=endpoint,
        method=method,
        msg_id=msg_id,
    )
    return payload


def _write_message(proc: subprocess.Popen, message: dict[str, Any]) -> None:
    if proc.stdin is None:
        raise RuntimeError("MCP server stdin unavailable")
    body = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    proc.stdin.write(header + body)
    proc.stdin.flush()


def _read_message(proc: subprocess.Popen, timeout: float) -> dict[str, Any]:
    if proc.stdout is None:
        raise RuntimeError("MCP server stdout unavailable")

    deadline = time.monotonic() + timeout
    first_line = _readline_with_timeout(proc.stdout, deadline)
    if not first_line:
        raise RuntimeError("MCP server closed stdout")

    # Backward-compatible fallback for newline-delimited JSON emitters.
    stripped = first_line.strip()
    if stripped.startswith(b"{"):
        return json.loads(stripped.decode("utf-8", errors="replace"))

    headers: dict[str, str] = {}
    _parse_header_line(headers, first_line)
    while True:
        line = _readline_with_timeout(proc.stdout, deadline)
        if line in (b"\r\n", b"\n", b""):
            break
        _parse_header_line(headers, line)

    content_length_raw = headers.get("content-length")
    if content_length_raw is None:
        raise RuntimeError(f"MCP message missing Content-Length header: {headers}")
    try:
        content_length = int(content_length_raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid Content-Length header: {content_length_raw!r}"
        ) from exc

    body = _read_exact_with_timeout(proc.stdout, deadline, content_length)
    return json.loads(body.decode("utf-8", errors="replace"))


def _parse_header_line(headers: dict[str, str], line: bytes) -> None:
    decoded = line.decode("ascii", errors="replace").strip()
    if ":" not in decoded:
        return
    key, value = decoded.split(":", 1)
    headers[key.strip().lower()] = value.strip()


def _readline_with_timeout(stream, deadline: float) -> bytes:
    remaining = max(0.0, deadline - time.monotonic())
    if remaining == 0:
        raise TimeoutError("Timed out while waiting for MCP header line")
    ready, _, _ = select.select([stream], [], [], remaining)
    if not ready:
        raise TimeoutError("Timed out while waiting for MCP header line")
    line = stream.readline()
    if line == b"":
        raise RuntimeError("MCP server closed stdout")
    return line


def _read_exact_with_timeout(stream, deadline: float, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining_bytes = size
    while remaining_bytes > 0:
        remaining_time = max(0.0, deadline - time.monotonic())
        if remaining_time == 0:
            raise TimeoutError("Timed out while reading MCP message body")
        ready, _, _ = select.select([stream], [], [], remaining_time)
        if not ready:
            raise TimeoutError("Timed out while reading MCP message body")
        chunk = stream.read(remaining_bytes)
        if not chunk:
            raise RuntimeError("MCP server closed stdout during message body")
        chunks.append(chunk)
        remaining_bytes -= len(chunk)
    return b"".join(chunks)


def _normalize_install_cmd(install_cmd: str | list[str]) -> list[str]:
    if isinstance(install_cmd, str):
        return shlex.split(install_cmd)
    if isinstance(install_cmd, list):
        return [str(part) for part in install_cmd if str(part).strip()]
    return []


def _assert_stdio_server_allowed(
    server: MCPServer,
    logger: RunLogger | None,
    *,
    allow_node_stdio: bool = False,
) -> None:
    command_name = Path(server.command).name.lower()
    args_text = " ".join(server.args).lower()
    is_node_family = command_name in _NODE_STDIO_COMMANDS or any(
        marker in args_text
        for marker in (
            "@modelcontextprotocol/",
            "@playwright/mcp",
            "server-filesystem",
            "playwright-mcp",
        )
    )
    if not is_node_family:
        return
    if allow_node_stdio:
        return

    message = (
        "Node-family MCP servers are blocked for stdio transport in jelly.mcp. "
        "Use a Python-native MCP server over stdio, or launch Node servers as "
        "HTTP/SSE sidecars and connect via a Python client. "
        f"Received command: {server.command} {' '.join(server.args)}"
    )
    _log(
        logger,
        "ERROR",
        "start_server.node_stdio_blocked",
        server=server.name,
        command=server.command,
        args=server.args,
    )
    raise RuntimeError(message)


def _check_server_availability(server: MCPServer) -> tuple[bool, str]:
    if server.transport == "http_sse":
        endpoint = (server.endpoint or "").strip()
        if not endpoint:
            env_name = server.metadata.get("endpoint_env", "endpoint")
            return False, f"missing_endpoint ({env_name})"
        return True, "ready"

    command = (server.command or "").strip()
    if not command:
        return False, "missing_command"
    command_name = Path(command).name
    # Keep path-like commands valid if the file exists.
    if "/" in command and Path(command).exists():
        return True, "ready"
    if os.path.isabs(command) and Path(command).exists():
        return True, "ready"
    if shutil.which(command_name) is None:
        return False, f"missing_command ({command_name})"
    return True, "ready"


def _preflight_server(server: MCPServer, logger: RunLogger | None) -> None:
    if server.name.lower() != "filesystem":
        return
    workspace = _filesystem_workspace(server)
    if workspace is None:
        return
    path = Path(workspace)
    path.mkdir(parents=True, exist_ok=True)
    _log(
        logger,
        "INFO",
        "start_server.filesystem_preflight",
        server=server.name,
        workspace=str(path.resolve()),
    )


def _filesystem_workspace(server: MCPServer) -> str | None:
    for idx, arg in enumerate(server.args):
        if "server-filesystem" in arg and idx + 1 < len(server.args):
            return server.args[idx + 1]
    if server.name.lower() == "filesystem" and server.args:
        candidate = server.args[-1]
        if candidate and not candidate.startswith("-"):
            return candidate
    return None


def _stderr_tail(proc: subprocess.Popen, max_chars: int = 2000) -> str:
    if proc.stderr is None:
        return ""
    if proc.poll() is None:
        return ""
    try:
        data = proc.stderr.read()
    except OSError:
        return ""
    if not data:
        return ""
    text = data.decode("utf-8", errors="replace")
    return text[-max_chars:]


def _log(
    logger: RunLogger | None,
    level: str,
    operation: str,
    **fields: Any,
) -> None:
    if logger:
        logger.event(level, "mcp", operation, **fields)
