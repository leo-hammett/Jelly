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

    def fake_call_tool(_proc, _tool_name, _arguments, **_kwargs):
        return {"content": [{"type": "text", "text": "ok"}]}

    def fake_stop_server(_proc):
        return None

    monkeypatch.setattr("jelly.agents.test_executor.start_server", fake_start_server)
    monkeypatch.setattr("jelly.agents.test_executor.call_tool", fake_call_tool)
    monkeypatch.setattr("jelly.agents.test_executor.stop_server", fake_stop_server)

    results = executor.run_mcp_tests(plan, project_dir=".")

    assert results["total_tests"] == 2
    assert results["passed"] == 1
    assert results["failed"] == 1
    assert results["all_passed"] is False
