from __future__ import annotations

import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from jelly.config import Config
from jelly.mcp import MCPServer, install_server, sidecar_install_command, sidecar_launch_command
from jelly.run_logging import RunLogger


@dataclass
class ManagedSidecar:
    name: str
    endpoint: str
    port: int
    process: subprocess.Popen
    log_path: Path


class MCPSidecarManager:
    """Manage dynamic MCP sidecar install/launch/cleanup for one run."""

    def __init__(
        self,
        config: Config,
        project_dir: str,
        logger: RunLogger | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.project_dir = Path(project_dir).resolve()
        self.state_dir = self.project_dir / ".mcp" / "dynamic_sidecars"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._managed: dict[str, ManagedSidecar] = {}
        self._used_ports: set[int] = set()

        # Summary counters for reporting.
        self.installed_servers: set[str] = set()
        self.launched_servers: set[str] = set()
        self.reused_servers: set[str] = set()
        self.failed_servers: set[str] = set()

    def install_if_needed(self, server: MCPServer) -> bool:
        cmd = sidecar_install_command(server)
        if not cmd:
            return True
        install_spec = MCPServer(
            name=server.name,
            install_cmd=cmd,
        )
        ok = install_server(
            install_spec,
            timeout=int(self.config.mcp_dynamic_install_timeout_seconds),
            logger=self.logger,
        )
        if ok:
            self.installed_servers.add(server.name)
            _log(self.logger, "INFO", "install_if_needed.complete", server=server.name)
        else:
            self.failed_servers.add(server.name)
            _log(self.logger, "ERROR", "install_if_needed.failed", server=server.name)
        return ok

    def launch_sidecar(self, server: MCPServer) -> str:
        if not self.config.mcp_dynamic_sidecars_enabled:
            raise RuntimeError("Dynamic sidecar provisioning is disabled by config.")

        existing = self._managed.get(server.name)
        if existing and self._is_running(existing.process):
            self.reused_servers.add(server.name)
            return existing.endpoint

        if len(self._managed) >= int(self.config.mcp_dynamic_max_sidecars_per_run):
            raise RuntimeError(
                "Maximum dynamic sidecars per run reached "
                f"({self.config.mcp_dynamic_max_sidecars_per_run})."
            )

        if not self.install_if_needed(server):
            raise RuntimeError(f"Failed to install dynamic sidecar for '{server.name}'.")

        port = server.sidecar_port or self._allocate_port()
        host = self.config.mcp_dynamic_sidecar_host
        endpoint = f"http://{host}:{port}/mcp"
        log_path = self.state_dir / f"{_safe_name(server.name)}.log"
        launch_cmd = sidecar_launch_command(server)
        sidecar_script = Path(__file__).resolve().parent / "mcp_sidecar.py"

        log_handle = log_path.open("ab")
        proc = subprocess.Popen(
            [
                sys.executable,
                str(sidecar_script),
                "--name",
                server.name,
                "--host",
                host,
                "--port",
                str(port),
                "--timeout-seconds",
                str(float(self.config.mcp_dynamic_startup_timeout_seconds)),
                "--cwd",
                str(self.project_dir),
                "--",
                *launch_cmd,
            ],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(self.project_dir),
            text=False,
        )
        log_handle.close()
        _log(
            self.logger,
            "INFO",
            "launch_sidecar.start",
            server=server.name,
            endpoint=endpoint,
            port=port,
            launch_cmd=launch_cmd,
        )
        if not self.health_check(endpoint, timeout_seconds=float(self.config.mcp_dynamic_startup_timeout_seconds)):
            self.failed_servers.add(server.name)
            try:
                self._stop_process(proc)
            finally:
                tail = self._log_tail(log_path)
                raise RuntimeError(
                    f"Dynamic sidecar '{server.name}' failed health check at {endpoint}. "
                    f"log_tail={tail}"
                )

        managed = ManagedSidecar(
            name=server.name,
            endpoint=endpoint,
            port=port,
            process=proc,
            log_path=log_path,
        )
        self._managed[server.name] = managed
        self._used_ports.add(port)
        self.launched_servers.add(server.name)
        _log(
            self.logger,
            "INFO",
            "launch_sidecar.ready",
            server=server.name,
            endpoint=endpoint,
            port=port,
        )
        return endpoint

    def ensure_running(self, server: MCPServer) -> str:
        endpoint = self.get_endpoint(server.name)
        if endpoint:
            self.reused_servers.add(server.name)
            return endpoint
        return self.launch_sidecar(server)

    def health_check(self, endpoint: str, timeout_seconds: float) -> bool:
        base = endpoint[:-4] if endpoint.endswith("/mcp") else endpoint
        health_url = base.rstrip("/") + "/health"
        deadline = time.monotonic() + max(1.0, timeout_seconds)
        while time.monotonic() < deadline:
            try:
                with urlopen(health_url, timeout=1.5) as resp:
                    if resp.status == 200:
                        return True
            except URLError:
                pass
            time.sleep(0.2)
        return False

    def get_endpoint(self, server_name: str) -> str | None:
        managed = self._managed.get(server_name)
        if not managed:
            return None
        if not self._is_running(managed.process):
            return None
        return managed.endpoint

    def stop_all(self) -> None:
        for managed in list(self._managed.values()):
            self._stop_process(managed.process)
            _log(
                self.logger,
                "INFO",
                "stop_all.stopped",
                server=managed.name,
                endpoint=managed.endpoint,
                port=managed.port,
            )
        self._managed.clear()
        self._used_ports.clear()

    def summary(self) -> dict[str, Any]:
        return {
            "dynamic_installed": len(self.installed_servers),
            "dynamic_launched": len(self.launched_servers),
            "dynamic_reused": len(self.reused_servers),
            "dynamic_failed": len(self.failed_servers),
            "dynamic_failed_servers": sorted(self.failed_servers),
        }

    def _allocate_port(self) -> int:
        start = int(self.config.mcp_dynamic_sidecar_base_port)
        span = int(self.config.mcp_dynamic_sidecar_port_span)
        for port in range(start, start + span):
            if port in self._used_ports:
                continue
            if _port_is_free(self.config.mcp_dynamic_sidecar_host, port):
                return port
        raise RuntimeError(
            f"No free sidecar ports in range {start}-{start + span - 1}."
        )

    @staticmethod
    def _is_running(proc: subprocess.Popen) -> bool:
        return proc.poll() is None

    def _log_tail(self, path: Path, max_chars: int = 1200) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text[-max_chars:]

    @staticmethod
    def _stop_process(proc: subprocess.Popen) -> None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass


def _safe_name(value: str) -> str:
    return "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in value) or "sidecar"


def _port_is_free(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError:
        return False
    finally:
        sock.close()
    return True


def _log(
    logger: RunLogger | None,
    level: str,
    operation: str,
    **fields: Any,
) -> None:
    if logger:
        logger.event(level, "mcp_sidecar_manager", operation, **fields)
