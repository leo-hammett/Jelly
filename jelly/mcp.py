"""Thin utilities for installing and talking to MCP servers over stdio.

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
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    install_cmd: str | list[str] | None = None


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
) -> subprocess.Popen:
    """Start an MCP server subprocess. Returns the Popen handle.

    Waits for the process to be ready, then sends the JSON-RPC
    `initialize` handshake before returning.
    """
    _assert_stdio_server_allowed(server, logger)
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


def _assert_stdio_server_allowed(server: MCPServer, logger: RunLogger | None) -> None:
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
