from __future__ import annotations

import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from jelly.config import Config
from jelly.mcp import (
    MCPServer,
    install_server,
    native_sidecar_launch_command,
    preferred_sidecar_launch_mode,
    sidecar_install_command,
    sidecar_launch_command,
    start_server_for_transport,
)
from jelly.run_logging import RunLogger


@dataclass
class ManagedSidecar:
    name: str
    endpoint: str
    port: int
    launch_mode: str
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
        self.failed_install_servers: set[str] = set()
        self.failed_install_packages: set[str] = set()
        self.launch_modes_by_server: dict[str, str] = {}

    def install_if_needed(self, server: MCPServer) -> bool:
        package_name = (server.sidecar_package or "").strip()
        if server.name in self.failed_install_servers:
            _log(
                self.logger,
                "WARNING",
                "install_if_needed.skipped_failed_server",
                server=server.name,
            )
            return False
        if package_name and package_name in self.failed_install_packages:
            _log(
                self.logger,
                "WARNING",
                "install_if_needed.skipped_failed_package",
                server=server.name,
                package=package_name,
            )
            self.failed_install_servers.add(server.name)
            return False

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
            self.failed_install_servers.add(server.name)
            if package_name:
                self.failed_install_packages.add(package_name)
            _log(self.logger, "ERROR", "install_if_needed.failed", server=server.name)
        return ok

    def launch_sidecar(self, server: MCPServer) -> str:
        if not self.config.mcp_dynamic_sidecars_enabled:
            raise RuntimeError("Dynamic sidecar provisioning is disabled by config.")
        if server.name in self.failed_servers:
            raise RuntimeError(
                f"Dynamic sidecar '{server.name}' was previously marked failed in this run."
            )

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
        launch_mode = preferred_sidecar_launch_mode(server)
        native_cmd = native_sidecar_launch_command(server, host, port)
        if launch_mode == "native_sse" and native_cmd:
            process_cmd = native_cmd
        else:
            launch_mode = "bridge"
            launch_cmd = sidecar_launch_command(server)
            sidecar_script = Path(__file__).resolve().parent / "mcp_sidecar.py"
            process_cmd = [
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
            ]

        proc = self._spawn_process(process_cmd, log_path)
        _log(
            self.logger,
            "INFO",
            "launch_sidecar.start",
            server=server.name,
            endpoint=endpoint,
            port=port,
            launch_mode=launch_mode,
            launch_cmd=process_cmd,
        )
        healthy = self.health_check(
            endpoint,
            timeout_seconds=float(self.config.mcp_dynamic_startup_timeout_seconds),
            server_name=server.name,
            launch_mode=launch_mode,
            proc=proc,
        )
        if not healthy and launch_mode == "native_sse":
            _log(
                self.logger,
                "WARNING",
                "launch_sidecar.native_failed_fallback_bridge",
                server=server.name,
                endpoint=endpoint,
            )
            self._stop_process(proc)
            launch_mode = "bridge"
            launch_cmd = sidecar_launch_command(server)
            sidecar_script = Path(__file__).resolve().parent / "mcp_sidecar.py"
            process_cmd = [
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
            ]
            proc = self._spawn_process(process_cmd, log_path)
            healthy = self.health_check(
                endpoint,
                timeout_seconds=float(self.config.mcp_dynamic_startup_timeout_seconds),
                server_name=server.name,
                launch_mode=launch_mode,
                proc=proc,
            )

        if not healthy:
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
            launch_mode=launch_mode,
            process=proc,
            log_path=log_path,
        )
        self._managed[server.name] = managed
        self._used_ports.add(port)
        self.launched_servers.add(server.name)
        self.launch_modes_by_server[server.name] = launch_mode
        _log(
            self.logger,
            "INFO",
            "launch_sidecar.ready",
            server=server.name,
            endpoint=endpoint,
            port=port,
            launch_mode=launch_mode,
        )
        return endpoint

    def ensure_running(self, server: MCPServer) -> str:
        if server.name in self.failed_servers:
            raise RuntimeError(
                f"Dynamic sidecar '{server.name}' is quarantined after prior failure."
            )
        endpoint = self.get_endpoint(server.name)
        if endpoint:
            self.reused_servers.add(server.name)
            return endpoint
        return self.launch_sidecar(server)

    def health_check(
        self,
        endpoint: str,
        timeout_seconds: float,
        server_name: str,
        launch_mode: str,
        proc: subprocess.Popen,
    ) -> bool:
        deadline = time.monotonic() + max(1.0, timeout_seconds)
        last_error = ""
        while time.monotonic() < deadline:
            if not self._is_running(proc):
                _log(
                    self.logger,
                    "ERROR",
                    "health_check.process_exited",
                    server=server_name,
                    launch_mode=launch_mode,
                    returncode=proc.returncode,
                )
                return False

            try:
                if launch_mode == "native_sse":
                    probe = MCPServer(
                        name=server_name,
                        transport="http_sse",
                        endpoint=endpoint,
                    )
                    remaining = max(0.5, min(3.0, deadline - time.monotonic()))
                    start_server_for_transport(
                        probe,
                        request_timeout=remaining,
                        logger=self.logger,
                    )
                    return True

                base = endpoint[:-4] if endpoint.endswith("/mcp") else endpoint
                health_url = base.rstrip("/") + "/health"
                with urlopen(health_url, timeout=1.5) as resp:
                    if resp.status == 200:
                        return True
            except Exception as exc:
                last_error = str(exc)
            time.sleep(0.2)
        _log(
            self.logger,
            "ERROR",
            "health_check.timeout",
            server=server_name,
            launch_mode=launch_mode,
            endpoint=endpoint,
            error_message=last_error,
        )
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
                launch_mode=managed.launch_mode,
            )
        self._managed.clear()
        self._used_ports.clear()

    def summary(self) -> dict[str, Any]:
        launch_mode_counts: dict[str, int] = {}
        for launch_mode in self.launch_modes_by_server.values():
            launch_mode_counts[launch_mode] = launch_mode_counts.get(launch_mode, 0) + 1
        return {
            "dynamic_installed": len(self.installed_servers),
            "dynamic_launched": len(self.launched_servers),
            "dynamic_reused": len(self.reused_servers),
            "dynamic_failed": len(self.failed_servers),
            "dynamic_failed_servers": sorted(self.failed_servers),
            "dynamic_failed_install_servers": sorted(self.failed_install_servers),
            "dynamic_failed_install_packages": sorted(self.failed_install_packages),
            "dynamic_launch_modes": launch_mode_counts,
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

    def _spawn_process(self, command: list[str], log_path: Path) -> subprocess.Popen:
        log_handle = log_path.open("ab")
        try:
            return subprocess.Popen(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                cwd=str(self.project_dir),
                text=False,
            )
        finally:
            log_handle.close()

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
