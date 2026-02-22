import io

import jelly.mcp as mcp
import jelly.mcp_sidecar_manager as sidecar_manager
from jelly.config import Config


def test_install_server_uses_non_shell_command(monkeypatch) -> None:
    captured = {}

    class _Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, shell, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["shell"] = shell
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        return _Result()

    monkeypatch.setattr(mcp.subprocess, "run", fake_run)

    server = mcp.MCPServer(
        name="playwright",
        command="python",
        args=["server.py"],
        install_cmd="npm install -g @playwright/mcp",
    )

    assert mcp.install_server(server) is True
    assert captured["shell"] is False
    assert captured["cmd"] == ["npm", "install", "-g", "@playwright/mcp"]


def test_start_server_includes_stderr_on_boot_failure(monkeypatch) -> None:
    class _FakeProc:
        def __init__(self) -> None:
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO(b"boom stderr")
            self.returncode = 23

        def poll(self):
            return self.returncode

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            return None

    monkeypatch.setattr(mcp.subprocess, "Popen", lambda *args, **kwargs: _FakeProc())

    server = mcp.MCPServer(name="broken", command="python", args=["broken_server.py"])
    try:
        mcp.start_server(server, startup_wait=0.2)
    except RuntimeError as exc:
        assert "boom stderr" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError from startup failure")


def test_start_server_blocks_node_family_stdio() -> None:
    server = mcp.MCPServer(
        name="filesystem",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp/workspace"],
    )
    try:
        mcp.start_server(server)
    except RuntimeError as exc:
        assert "blocked for stdio transport" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError from node stdio policy guard")


def test_build_bootstrap_servers_reads_sidecar_endpoints(monkeypatch, tmp_path) -> None:
    config = Config()
    monkeypatch.setenv(config.mcp_filesystem_endpoint_env, "http://fs.example/mcp")
    monkeypatch.setenv(config.mcp_browser_endpoint_env, "http://browser.example/mcp")

    servers = mcp.build_bootstrap_servers(config, str(tmp_path))
    assert [s.name for s in servers] == ["filesystem", "browser"]
    assert all(s.transport == "http_sse" for s in servers)
    assert servers[0].endpoint == "http://fs.example/mcp"
    assert servers[1].endpoint == "http://browser.example/mcp"


def test_start_server_for_transport_http_initialize_error_blocks_start(monkeypatch) -> None:
    server = mcp.MCPServer(
        name="browser",
        transport="http_sse",
        endpoint="http://localhost:18888/mcp",
    )
    notification_calls = {"count": 0}

    monkeypatch.setattr(
        mcp,
        "_send_jsonrpc_http",
        lambda *_args, **_kwargs: {"error": {"code": -32000, "message": "boom"}},
    )
    monkeypatch.setattr(
        mcp,
        "_send_notification_http",
        lambda *_args, **_kwargs: notification_calls.__setitem__(
            "count", notification_calls["count"] + 1
        ),
    )

    try:
        mcp.start_server_for_transport(server, request_timeout=1)
    except RuntimeError as exc:
        assert "initialize returned error" in str(exc)
    else:
        raise AssertionError("Expected initialize error to fail startup")
    assert notification_calls["count"] == 0


def test_start_server_for_transport_http_sends_initialized_notification(monkeypatch) -> None:
    server = mcp.MCPServer(
        name="browser",
        transport="http_sse",
        endpoint="http://localhost:18889/mcp",
    )
    calls: list[tuple[str, str]] = []

    def fake_send_jsonrpc_http(_endpoint, method, _params, **_kwargs):
        calls.append(("request", method))
        return {"result": {"serverInfo": {"name": "ok"}}}

    def fake_send_notification_http(_endpoint, method, **_kwargs):
        calls.append(("notification", method))

    monkeypatch.setattr(mcp, "_send_jsonrpc_http", fake_send_jsonrpc_http)
    monkeypatch.setattr(mcp, "_send_notification_http", fake_send_notification_http)

    proc = mcp.start_server_for_transport(server, request_timeout=1)
    assert proc is None
    assert calls == [
        ("request", "initialize"),
        ("notification", "notifications/initialized"),
    ]


def test_bootstrap_servers_marks_missing_endpoints_unavailable(monkeypatch, tmp_path) -> None:
    config = Config()
    monkeypatch.delenv(config.mcp_filesystem_endpoint_env, raising=False)
    monkeypatch.delenv(config.mcp_browser_endpoint_env, raising=False)

    result = mcp.bootstrap_servers(config, str(tmp_path))
    assert result.requested_servers == ["filesystem", "browser"]
    assert result.available_servers == []
    assert "filesystem" in result.unavailable
    assert "browser" in result.unavailable


def test_playwright_native_sidecar_launch_mode_and_command() -> None:
    server = mcp.MCPServer(
        name="browser",
        transport="http_sse",
        dynamic_sidecar=True,
        sidecar_package="@playwright/mcp",
        sidecar_command=["npx", "-y", "@playwright/mcp"],
    )
    assert mcp.preferred_sidecar_launch_mode(server) == "native_sse"
    cmd = mcp.native_sidecar_launch_command(server, "127.0.0.1", 7788)
    assert cmd is not None
    assert "--host" in cmd
    assert "--port" in cmd
    assert "127.0.0.1" in cmd
    assert "7788" in cmd


def test_call_tool_for_server_http_transport(monkeypatch) -> None:
    captured = {}

    def fake_send(endpoint, method, params, **_kwargs):
        captured["endpoint"] = endpoint
        captured["method"] = method
        captured["params"] = params
        return {"result": {"content": [{"type": "text", "text": "ok"}]}}

    monkeypatch.setattr(mcp, "_send_jsonrpc_http", fake_send)
    server = mcp.MCPServer(
        name="browser",
        transport="http_sse",
        endpoint="http://localhost:18080/mcp",
    )
    result = mcp.call_tool_for_server(server, None, "snapshot", {"interactive": True})

    assert captured["endpoint"] == "http://localhost:18080/mcp"
    assert captured["method"] == "tools/call"
    assert captured["params"]["name"] == "snapshot"
    assert result["content"][0]["text"] == "ok"


def test_can_lazy_provision_for_dynamic_http_server() -> None:
    server = mcp.MCPServer(
        name="github",
        transport="http_sse",
        endpoint=None,
        dynamic_sidecar=True,
        sidecar_package="@modelcontextprotocol/server-github",
        sidecar_command=["npx", "-y", "@modelcontextprotocol/server-github"],
    )
    assert mcp.can_lazy_provision(server) is True


def test_sidecar_command_and_install_defaults_from_package() -> None:
    server = mcp.MCPServer(
        name="github",
        transport="http_sse",
        dynamic_sidecar=True,
        sidecar_package="@modelcontextprotocol/server-github",
    )
    assert mcp.sidecar_launch_command(server) == [
        "npx",
        "-y",
        "@modelcontextprotocol/server-github",
    ]
    assert mcp.sidecar_install_command(server) == [
        "npm",
        "install",
        "-g",
        "@modelcontextprotocol/server-github",
    ]


def test_sidecar_manager_launches_and_reuses(monkeypatch, tmp_path) -> None:
    config = Config()
    config.mcp_dynamic_sidecars_enabled = True
    config.mcp_dynamic_sidecar_base_port = 8810
    config.mcp_dynamic_sidecar_port_span = 5
    launches = []

    class _FakeProc:
        def __init__(self) -> None:
            self._returncode = None

        def poll(self):
            return self._returncode

        def terminate(self):
            self._returncode = 0

        def wait(self, timeout=None):  # noqa: ARG002
            return 0

        def kill(self):
            self._returncode = -9

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ARG002
            return False

    def fake_popen(cmd, **_kwargs):
        launches.append(cmd)
        return _FakeProc()

    monkeypatch.setattr(sidecar_manager, "install_server", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sidecar_manager.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(sidecar_manager, "_port_is_free", lambda _host, _port: True)
    monkeypatch.setattr(sidecar_manager, "urlopen", lambda *_args, **_kwargs: _Resp())

    manager = sidecar_manager.MCPSidecarManager(config, str(tmp_path))
    server = mcp.MCPServer(
        name="github",
        transport="http_sse",
        dynamic_sidecar=True,
        sidecar_package="@modelcontextprotocol/server-github",
        sidecar_command=["npx", "-y", "@modelcontextprotocol/server-github"],
    )
    endpoint1 = manager.ensure_running(server)
    endpoint2 = manager.ensure_running(server)

    assert endpoint1 == endpoint2
    assert len(launches) == 1
    summary = manager.summary()
    assert summary["dynamic_launched"] == 1
    assert summary["dynamic_reused"] == 1
    manager.stop_all()


def test_sidecar_manager_caches_failed_package_installs(monkeypatch, tmp_path) -> None:
    config = Config()
    config.mcp_dynamic_sidecars_enabled = True
    attempts = {"count": 0}

    def fake_install_server(*_args, **_kwargs):
        attempts["count"] += 1
        return False

    monkeypatch.setattr(sidecar_manager, "install_server", fake_install_server)
    manager = sidecar_manager.MCPSidecarManager(config, str(tmp_path))
    server_a = mcp.MCPServer(
        name="fetch_a",
        transport="http_sse",
        dynamic_sidecar=True,
        sidecar_package="@example/fetch-sidecar",
        sidecar_command=["npx", "-y", "@example/fetch-sidecar"],
    )
    server_b = mcp.MCPServer(
        name="fetch_b",
        transport="http_sse",
        dynamic_sidecar=True,
        sidecar_package="@example/fetch-sidecar",
        sidecar_command=["npx", "-y", "@example/fetch-sidecar"],
    )

    assert manager.install_if_needed(server_a) is False
    assert manager.install_if_needed(server_b) is False
    assert attempts["count"] == 1
    summary = manager.summary()
    assert summary["dynamic_failed_install_servers"] == ["fetch_a", "fetch_b"]
    assert summary["dynamic_failed_install_packages"] == ["@example/fetch-sidecar"]


def test_sidecar_manager_prefers_native_launch_for_playwright(monkeypatch, tmp_path) -> None:
    config = Config()
    config.mcp_dynamic_sidecars_enabled = True
    config.mcp_dynamic_sidecar_base_port = 8820
    config.mcp_dynamic_sidecar_port_span = 3
    launches = []

    class _FakeProc:
        def __init__(self) -> None:
            self._returncode = None

        def poll(self):
            return self._returncode

        def terminate(self):
            self._returncode = 0

        def wait(self, timeout=None):  # noqa: ARG002
            return 0

        def kill(self):
            self._returncode = -9

    monkeypatch.setattr(sidecar_manager, "install_server", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sidecar_manager, "_port_is_free", lambda _host, _port: True)
    monkeypatch.setattr(
        sidecar_manager,
        "start_server_for_transport",
        lambda _server, **_kwargs: None,
    )
    monkeypatch.setattr(
        sidecar_manager.subprocess,
        "Popen",
        lambda cmd, **_kwargs: launches.append(cmd) or _FakeProc(),
    )

    manager = sidecar_manager.MCPSidecarManager(config, str(tmp_path))
    server = mcp.MCPServer(
        name="browser_dynamic",
        transport="http_sse",
        dynamic_sidecar=True,
        sidecar_package="@playwright/mcp",
        sidecar_command=["npx", "-y", "@playwright/mcp"],
    )

    endpoint = manager.ensure_running(server)
    assert endpoint.endswith("/mcp")
    assert launches
    assert launches[0][:3] == ["npx", "-y", "@playwright/mcp"]
    summary = manager.summary()
    assert summary["dynamic_launch_modes"] == {"native_sse": 1}
    manager.stop_all()
