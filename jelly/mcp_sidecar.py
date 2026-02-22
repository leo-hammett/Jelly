#!/usr/bin/env python3
"""Small HTTP JSON-RPC bridge for stdio MCP servers.

This process runs a single MCP stdio server and exposes:
- GET /health -> {"ok": true, "name": "..."}
- POST /mcp   -> forwards JSON-RPC to MCP stdio process
"""

from __future__ import annotations

import argparse
import json
import select
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class MCPBridge:
    def __init__(
        self,
        name: str,
        cmd: list[str],
        timeout_seconds: float,
        cwd: str | None = None,
    ) -> None:
        self.name = name
        self.cmd = cmd
        self.timeout_seconds = timeout_seconds
        self.cwd = cwd
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._proc = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            cwd=self.cwd,
        )

    def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
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

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        proc = self._proc
        if proc is None:
            raise RuntimeError("MCP process is not started")
        if proc.poll() is not None:
            raise RuntimeError(
                f"MCP process exited with code {proc.returncode} before request"
            )
        if "id" not in payload:
            raise RuntimeError("Sidecar requires JSON-RPC requests with an 'id'")

        target_id = payload["id"]
        with self._lock:
            self._write_message(proc, payload)
            deadline = time.monotonic() + self.timeout_seconds
            while True:
                remaining = max(0.0, deadline - time.monotonic())
                if remaining == 0:
                    raise TimeoutError(
                        f"Timed out waiting for MCP response from '{self.name}'"
                    )
                response = self._read_message(proc, remaining)
                if response.get("id") == target_id:
                    return response

    @staticmethod
    def _write_message(proc: subprocess.Popen, message: dict[str, Any]) -> None:
        if proc.stdin is None:
            raise RuntimeError("MCP stdin is unavailable")
        body = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        proc.stdin.write(header + body)
        proc.stdin.flush()

    def _read_message(
        self,
        proc: subprocess.Popen,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if proc.stdout is None:
            raise RuntimeError("MCP stdout is unavailable")
        deadline = time.monotonic() + timeout_seconds
        first_line = self._readline_with_timeout(proc.stdout, deadline)
        if not first_line:
            raise RuntimeError("MCP server closed stdout")

        # Support newline-delimited JSON output as a fallback.
        stripped = first_line.strip()
        if stripped.startswith(b"{"):
            return json.loads(stripped.decode("utf-8", errors="replace"))

        headers: dict[str, str] = {}
        self._parse_header_line(headers, first_line)
        while True:
            line = self._readline_with_timeout(proc.stdout, deadline)
            if line in (b"\r\n", b"\n", b""):
                break
            self._parse_header_line(headers, line)

        content_length_raw = headers.get("content-length")
        if content_length_raw is None:
            raise RuntimeError("MCP message missing Content-Length header")
        try:
            content_length = int(content_length_raw)
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid Content-Length header: {content_length_raw!r}"
            ) from exc

        body = self._read_exact_with_timeout(proc.stdout, deadline, content_length)
        return json.loads(body.decode("utf-8", errors="replace"))

    @staticmethod
    def _parse_header_line(headers: dict[str, str], line: bytes) -> None:
        decoded = line.decode("ascii", errors="replace").strip()
        if ":" not in decoded:
            return
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()

    @staticmethod
    def _readline_with_timeout(stream, deadline: float) -> bytes:
        remaining = max(0.0, deadline - time.monotonic())
        if remaining == 0:
            raise TimeoutError("Timed out waiting for MCP header line")
        ready, _, _ = select.select([stream], [], [], remaining)
        if not ready:
            raise TimeoutError("Timed out waiting for MCP header line")
        line = stream.readline()
        if line == b"":
            raise RuntimeError("MCP server closed stdout")
        return line

    @staticmethod
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


class SidecarHandler(BaseHTTPRequestHandler):
    server_version = "JellyMCPSidecar/0.1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._json_response(404, {"ok": False, "error": "not_found"})
            return
        self._json_response(200, {"ok": True, "name": self.server.bridge.name})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/mcp":
            self._json_response(404, {"ok": False, "error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json_response(400, {"ok": False, "error": "invalid_content_length"})
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
        except Exception as exc:
            self._json_response(400, {"ok": False, "error": f"invalid_json: {exc}"})
            return

        try:
            response = self.server.bridge.request(payload)
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "error": {"code": -32000, "message": str(exc)},
            }
        self._json_response(200, response)

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        # Keep output concise; launch.sh writes process logs to files.
        return

    def _json_response(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class SidecarHTTPServer(ThreadingHTTPServer):
    def __init__(self, host: str, port: int, bridge: MCPBridge) -> None:
        self.bridge = bridge
        super().__init__((host, port), SidecarHandler)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch MCP HTTP sidecar bridge")
    parser.add_argument("--name", required=True, help="Sidecar name for diagnostics")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument("--port", type=int, required=True, help="HTTP bind port")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="Per-request timeout forwarded to MCP stdio process",
    )
    parser.add_argument("--cwd", default=None, help="Optional working directory")
    parser.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command and args for the MCP stdio server after '--'",
    )
    args = parser.parse_args()
    if args.cmd and args.cmd[0] == "--":
        args.cmd = args.cmd[1:]
    if not args.cmd:
        parser.error("missing MCP command. Pass it after '--'.")
    return args


def main() -> int:
    args = _parse_args()
    bridge = MCPBridge(
        name=args.name,
        cmd=[str(part) for part in args.cmd],
        timeout_seconds=float(args.timeout_seconds),
        cwd=args.cwd,
    )
    bridge.start()
    server = SidecarHTTPServer(args.host, args.port, bridge)

    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        bridge.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
