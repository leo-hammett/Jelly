from jelly.agents.test_executor import TestExecutor as ExecutorAgent
from jelly.config import Config
from jelly.mcp import MCPServer, MCPTestPlan, MCPTestStep


def test_run_mcp_tests_continues_when_one_server_fails(monkeypatch) -> None:
    executor = ExecutorAgent(Config())

    plan = MCPTestPlan(
        servers=[
            MCPServer(name="good", command="noop"),
            MCPServer(name="bad", command="noop"),
        ],
        steps=[
            MCPTestStep(
                description="good step",
                server="good",
                tool="ok_tool",
                arguments={},
                expected="ok",
            ),
            MCPTestStep(
                description="bad step",
                server="bad",
                tool="bad_tool",
                arguments={},
                expected="ok",
            ),
        ],
    )

    class _Proc:
        pass

    def fake_start_server(server, **_kwargs):
        if server.name == "bad":
            raise RuntimeError("startup failed")
        return _Proc()

    def fake_call_tool(_server, _proc, _tool_name, _arguments, **_kwargs):
        return {"content": [{"type": "text", "text": "ok"}]}

    def fake_stop_server(_server, _proc):
        return None

    monkeypatch.setattr(
        "jelly.agents.test_executor.start_server_for_transport",
        fake_start_server,
    )
    monkeypatch.setattr(
        "jelly.agents.test_executor.call_tool_for_server",
        fake_call_tool,
    )
    monkeypatch.setattr(
        "jelly.agents.test_executor.stop_server_for_transport",
        fake_stop_server,
    )

    results = executor.run_mcp_tests(plan, project_dir=".")

    assert results["total_tests"] == 2
    assert results["passed"] == 1
    assert results["failed"] == 1
    assert results["all_passed"] is False
    summary = results["mcp_summary"]
    assert summary["servers_requested"] == 2
    assert summary["servers_available"] == 2
    assert summary["servers_started"] == 1
    assert summary["servers_failed"] == 1
    assert summary["steps_total"] == 2
    assert summary["steps_passed"] == 1
    assert summary["steps_failed"] == 1
    assert summary["failed_servers"] == ["bad"]


def test_run_mcp_tests_supports_http_sse_transport(monkeypatch) -> None:
    executor = ExecutorAgent(Config())
    plan = MCPTestPlan(
        servers=[
            MCPServer(
                name="browser",
                transport="http_sse",
                endpoint="http://localhost:18080/mcp",
            )
        ],
        steps=[
            MCPTestStep(
                description="browser step",
                server="browser",
                tool="snapshot",
                arguments={},
                expected="ok",
            )
        ],
    )

    monkeypatch.setattr(
        "jelly.agents.test_executor.start_server_for_transport",
        lambda _server, **_kwargs: None,
    )
    monkeypatch.setattr(
        "jelly.agents.test_executor.call_tool_for_server",
        lambda _server, _proc, _tool_name, _arguments, **_kwargs: {
            "content": [{"type": "text", "text": "ok"}]
        },
    )
    monkeypatch.setattr(
        "jelly.agents.test_executor.stop_server_for_transport",
        lambda _server, _proc: None,
    )

    results = executor.run_mcp_tests(plan, project_dir=".")

    assert results["all_passed"] is True
    assert results["passed"] == 1
    assert results["failed"] == 0
    assert results["mcp_summary"]["servers_started"] == 1


def test_run_mcp_tests_lazy_provisions_dynamic_sidecar(monkeypatch) -> None:
    class _Manager:
        def __init__(self) -> None:
            self.calls = 0

        def ensure_running(self, _server):
            self.calls += 1
            return "http://127.0.0.1:9901/mcp"

        def summary(self):
            return {
                "dynamic_installed": 1,
                "dynamic_launched": 1,
                "dynamic_reused": 0,
                "dynamic_failed_servers": [],
            }

    manager = _Manager()
    executor = ExecutorAgent(Config(), sidecar_manager=manager)
    plan = MCPTestPlan(
        servers=[
            MCPServer(
                name="github",
                transport="http_sse",
                endpoint=None,
                dynamic_sidecar=True,
                sidecar_package="@modelcontextprotocol/server-github",
                sidecar_command=["npx", "-y", "@modelcontextprotocol/server-github"],
            )
        ],
        steps=[
            MCPTestStep(
                description="dynamic step",
                server="github",
                tool="search_issues",
                arguments={},
                expected="ok",
            )
        ],
    )

    monkeypatch.setattr(
        "jelly.agents.test_executor.start_server_for_transport",
        lambda _server, **_kwargs: None,
    )
    monkeypatch.setattr(
        "jelly.agents.test_executor.call_tool_for_server",
        lambda _server, _proc, _tool_name, _arguments, **_kwargs: {
            "content": [{"type": "text", "text": "ok"}]
        },
    )
    monkeypatch.setattr(
        "jelly.agents.test_executor.stop_server_for_transport",
        lambda _server, _proc: None,
    )

    results = executor.run_mcp_tests(plan, project_dir=".")

    assert results["all_passed"] is True
    assert manager.calls == 1
    assert results["mcp_summary"]["dynamic_installed"] == 1
    assert results["mcp_summary"]["dynamic_launched"] == 1


def test_run_mcp_tests_retries_once_after_dynamic_provision(monkeypatch) -> None:
    class _Manager:
        def ensure_running(self, _server):
            return "http://127.0.0.1:9902/mcp"

        def summary(self):
            return {
                "dynamic_installed": 0,
                "dynamic_launched": 1,
                "dynamic_reused": 0,
                "dynamic_failed_servers": [],
            }

    executor = ExecutorAgent(Config(), sidecar_manager=_Manager())
    plan = MCPTestPlan(
        servers=[
            MCPServer(
                name="github",
                transport="http_sse",
                endpoint=None,
                dynamic_sidecar=True,
                sidecar_package="@modelcontextprotocol/server-github",
                sidecar_command=["npx", "-y", "@modelcontextprotocol/server-github"],
            )
        ],
        steps=[
            MCPTestStep(
                description="retry step",
                server="github",
                tool="search_issues",
                arguments={},
                expected="ok",
            )
        ],
    )
    attempts = {"count": 0}

    monkeypatch.setattr(
        "jelly.agents.test_executor.start_server_for_transport",
        lambda _server, **_kwargs: None,
    )

    def flaky_call(_server, _proc, _tool_name, _arguments, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("transient after provision")
        return {"content": [{"type": "text", "text": "ok"}]}

    monkeypatch.setattr("jelly.agents.test_executor.call_tool_for_server", flaky_call)
    monkeypatch.setattr(
        "jelly.agents.test_executor.stop_server_for_transport",
        lambda _server, _proc: None,
    )

    results = executor.run_mcp_tests(plan, project_dir=".")

    assert results["all_passed"] is True
    assert attempts["count"] == 2


def test_failed_mcp_step_is_skipped_and_passed_next_round(monkeypatch) -> None:
    executor = ExecutorAgent(Config())
    plan = MCPTestPlan(
        servers=[MCPServer(name="svc", command="noop")],
        steps=[
            MCPTestStep(
                description="flaky mcp step",
                server="svc",
                tool="do_thing",
                arguments={"x": 1},
                expected="ok",
            )
        ],
    )

    class _Proc:
        pass

    calls = {"count": 0}

    monkeypatch.setattr(
        "jelly.agents.test_executor.start_server_for_transport",
        lambda _server, **_kwargs: _Proc(),
    )

    def always_fail(_server, _proc, _tool_name, _arguments, **_kwargs):
        calls["count"] += 1
        raise RuntimeError("mcp failed once")

    monkeypatch.setattr(
        "jelly.agents.test_executor.call_tool_for_server",
        always_fail,
    )
    monkeypatch.setattr(
        "jelly.agents.test_executor.stop_server_for_transport",
        lambda _server, _proc: None,
    )

    first = executor.run_mcp_tests(plan, project_dir=".")
    second = executor.run_mcp_tests(plan, project_dir=".")

    assert first["all_passed"] is False
    assert first["failed"] == 1
    assert second["all_passed"] is True
    assert second["failed"] == 0
    assert second["passed"] == 1
    assert second["mcp_summary"]["steps_skipped_quarantined"] == 1
    assert calls["count"] == 1
