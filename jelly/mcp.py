"""Thin utilities for installing and talking to MCP servers over stdio."""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

_next_id = 0


@dataclass
class MCPServer:
    """Everything needed to start and talk to one MCP server."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    install_cmd: str | None = None


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


def install_server(server: MCPServer) -> bool:
    """Install an MCP server using its install_cmd (npm, pip, etc.).

    Returns True if install succeeded or no install_cmd was needed.
    """
    if not server.install_cmd:
        return True
    try:
        result = subprocess.run(
            server.install_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def start_server(server: MCPServer, startup_wait: float = 3.0) -> subprocess.Popen:
    """Start an MCP server subprocess. Returns the Popen handle.

    Waits for the process to be ready, then sends the JSON-RPC
    `initialize` handshake before returning.
    """
    env = {**os.environ, **server.env}
    proc = subprocess.Popen(
        [server.command, *server.args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    # npx / pip wrappers need a moment to bootstrap
    deadline = time.monotonic() + startup_wait
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"MCP server '{server.name}' exited during startup "
                f"(code {proc.returncode})"
            )
        time.sleep(0.3)

    _send_jsonrpc(proc, "initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "jelly", "version": "1.0"},
    })
    _send_notification(proc, "notifications/initialized")
    return proc


def call_tool(
    proc: subprocess.Popen, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Send a tools/call JSON-RPC request and return the result."""
    response = _send_jsonrpc(proc, "tools/call", {
        "name": tool_name,
        "arguments": arguments,
    })
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
    proc: subprocess.Popen, method: str, params: dict | None = None
) -> None:
    """Send a JSON-RPC 2.0 notification (no id, no response expected)."""
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


def _send_jsonrpc(proc: subprocess.Popen, method: str, params: dict) -> dict:
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
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()

    while True:
        ready, _, _ = select.select([proc.stdout], [], [], 30)
        if not ready:
            raise TimeoutError(f"MCP server did not respond to {method}")
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed stdout")
        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            continue
        if response.get("id") == msg_id:
            return response
