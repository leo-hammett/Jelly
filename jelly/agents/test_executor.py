from jelly.config import Config
from jelly.mcp import MCPTestPlan, call_tool, start_server, stop_server
from jelly.sandbox.runner import run_tests


class TestExecutor:
    """Runs tests and produces structured feedback.

    Mostly Python logic, minimal LLM usage.
    """

    def __init__(self, config: Config) -> None:
        """Initialize with config (for timeout settings)."""
        self.config = config

    def run(
        self, code_files: dict[str, str], test_files: dict[str, str]
    ) -> dict:
        """Run code against tests in a sandboxed subprocess.

        Delegates to sandbox.runner.run_tests.

        Args:
            code_files: {filename: code_content} for source files.
            test_files: {filename: test_content} for test files.

        Returns:
            Structured result dict with all_passed, total_tests,
            passed, failed, and failure_details.
        """
        return run_tests(code_files, test_files, self.config.test_timeout_seconds)

    @staticmethod
    def format_feedback(results: dict) -> str:
        """Format test failures into a readable markdown report for the Programmer.

        Example output:
            ## Test Results: 8/12 passed

            ### Failures:

            **test_edge_empty_list** (TestEdgeCases)
            - Error: AssertionError — Expected [], got None

        Args:
            results: The structured dict returned by run().

        Returns:
            Markdown-formatted feedback string.
        """
        total = results["total_tests"]
        passed = results["passed"]
        lines = [f"## Test Results: {passed}/{total} passed\n"]

        if results["failure_details"]:
            lines.append("### Failures:\n")
            for failure in results["failure_details"]:
                lines.append(f"**{failure['test_name']}**")
                lines.append(
                    f"- Error: {failure['error_type']} — {failure['error_message']}"
                )
                if failure.get("traceback"):
                    lines.append(f"- Traceback:\n```\n{failure['traceback']}\n```")
                lines.append("")

        return "\n".join(lines)

    def run_mcp_tests(self, plan: MCPTestPlan, project_dir: str) -> dict:
        """Start MCP servers, replay test steps, check results.

        Returns the same structured dict as run() so results can be merged.
        """
        if not plan.steps:
            return _empty_results()

        procs: dict[str, object] = {}
        try:
            for server in plan.servers:
                try:
                    procs[server.name] = start_server(server)
                except Exception as exc:
                    return {
                        "all_passed": False,
                        "total_tests": len(plan.steps),
                        "passed": 0,
                        "failed": len(plan.steps),
                        "failure_details": [{
                            "test_name": f"(start {server.name})",
                            "error_type": type(exc).__name__,
                            "error_message": str(exc)[:500],
                            "traceback": "",
                        }],
                    }

            passed = 0
            failed = 0
            failure_details: list[dict] = []

            for step in plan.steps:
                proc = procs.get(step.server)
                if proc is None:
                    failed += 1
                    failure_details.append({
                        "test_name": step.description,
                        "error_type": "ServerNotFound",
                        "error_message": f"No running server named '{step.server}'",
                        "traceback": "",
                    })
                    continue
                try:
                    result = call_tool(proc, step.tool, step.arguments)
                    content_parts = result.get("content", [])
                    text = " ".join(
                        item.get("text", "")
                        for item in content_parts
                        if isinstance(item, dict) and item.get("type") == "text"
                    )
                    if step.expected and step.expected.lower() not in text.lower():
                        failed += 1
                        failure_details.append({
                            "test_name": step.description,
                            "error_type": "AssertionError",
                            "error_message": (
                                f"Expected '{step.expected}' in result, "
                                f"got: {text[:300]}"
                            ),
                            "traceback": "",
                        })
                    else:
                        passed += 1
                except Exception as exc:
                    failed += 1
                    failure_details.append({
                        "test_name": step.description,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:500],
                        "traceback": "",
                    })

            total = passed + failed
            return {
                "all_passed": failed == 0 and total > 0,
                "total_tests": total,
                "passed": passed,
                "failed": failed,
                "failure_details": failure_details,
            }
        finally:
            for proc in procs.values():
                stop_server(proc)

    def run_all(
        self,
        code_files: dict[str, str],
        test_files: dict[str, str],
        mcp_plan: MCPTestPlan | None,
        project_dir: str,
    ) -> dict:
        """Run unit tests (pytest) and MCP tests, merge the results."""
        if test_files:
            unit_results = self.run(code_files, test_files)
        else:
            unit_results = _empty_results()

        if mcp_plan and mcp_plan.steps:
            mcp_results = self.run_mcp_tests(mcp_plan, project_dir)
            total = unit_results["total_tests"] + mcp_results["total_tests"]
            failed = unit_results["failed"] + mcp_results["failed"]
            return {
                "all_passed": failed == 0 and total > 0,
                "total_tests": total,
                "passed": unit_results["passed"] + mcp_results["passed"],
                "failed": failed,
                "failure_details": (
                    unit_results["failure_details"]
                    + mcp_results["failure_details"]
                ),
            }

        return unit_results


def _empty_results() -> dict:
    return {
        "all_passed": True,
        "total_tests": 0,
        "passed": 0,
        "failed": 0,
        "failure_details": [],
    }
