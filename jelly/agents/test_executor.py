from pathlib import Path

from jelly.config import Config
from jelly.mcp import MCPTestPlan, call_tool, start_server, stop_server
from jelly.run_logging import RunLogger
from jelly.sandbox.runner import run_tests


class TestExecutor:
    """Runs tests and produces structured feedback.

    Mostly Python logic, minimal LLM usage.
    """

    def __init__(self, config: Config, logger: RunLogger | None = None) -> None:
        """Initialize with config (for timeout settings)."""
        self.config = config
        self.logger = logger

    def _log(self, level: str, operation: str, **fields) -> None:
        if self.logger:
            self.logger.event(level, "test_executor", operation, **fields)

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
        self._log(
            "INFO",
            "run.start",
            code_files=len(code_files),
            test_files=len(test_files),
            timeout_seconds=self.config.test_timeout_seconds,
        )
        results = run_tests(
            code_files,
            test_files,
            self.config.test_timeout_seconds,
            logger=self.logger,
            keep_sandbox_on_failure=self.config.keep_sandbox_on_failure,
        )
        self._log(
            "INFO",
            "run.complete",
            all_passed=results.get("all_passed"),
            total_tests=results.get("total_tests"),
            failed=results.get("failed"),
        )
        return results

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
        startup_errors: dict[str, Exception] = {}
        self._log(
            "INFO",
            "run_mcp_tests.start",
            servers=len(plan.servers),
            steps=len(plan.steps),
            project_dir=str(Path(project_dir).resolve()),
        )
        try:
            for server in plan.servers:
                try:
                    self._log(
                        "INFO",
                        "run_mcp_tests.server_starting",
                        server=server.name,
                        command=server.command,
                        args=server.args,
                    )
                    procs[server.name] = start_server(
                        server,
                        startup_wait=float(self.config.mcp_test_timeout),
                        request_timeout=float(self.config.mcp_test_timeout),
                        logger=self.logger,
                    )
                    self._log(
                        "INFO",
                        "run_mcp_tests.server_started",
                        server=server.name,
                    )
                except Exception as exc:
                    startup_errors[server.name] = exc
                    self._log(
                        "ERROR",
                        "run_mcp_tests.server_start_failed",
                        server=server.name,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )

            passed = 0
            failed = 0
            failure_details: list[dict] = []

            for step in plan.steps:
                proc = procs.get(step.server)
                if proc is None:
                    failed += 1
                    exc = startup_errors.get(step.server)
                    reason = (
                        str(exc)[:500]
                        if exc is not None
                        else f"No running server named '{step.server}'"
                    )
                    err_type = type(exc).__name__ if exc is not None else "ServerNotFound"
                    failure_details.append({
                        "test_name": step.description,
                        "error_type": err_type,
                        "error_message": reason,
                        "traceback": "",
                    })
                    self._log(
                        "WARNING",
                        "run_mcp_tests.step_skipped_no_server",
                        step_description=step.description,
                        server=step.server,
                        available_servers=sorted(procs.keys()),
                    )
                    continue
                try:
                    result = call_tool(
                        proc,
                        step.tool,
                        step.arguments,
                        timeout=float(self.config.mcp_test_timeout),
                        logger=self.logger,
                        server_name=step.server,
                    )
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
                        self._log(
                            "WARNING",
                            "run_mcp_tests.step_assertion_failed",
                            step_description=step.description,
                            server=step.server,
                            expected=step.expected,
                            actual_excerpt=text[:300],
                        )
                    else:
                        passed += 1
                        self._log(
                            "INFO",
                            "run_mcp_tests.step_passed",
                            step_description=step.description,
                            server=step.server,
                            tool=step.tool,
                        )
                except Exception as exc:
                    failed += 1
                    failure_details.append({
                        "test_name": step.description,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:500],
                        "traceback": "",
                    })
                    self._log(
                        "ERROR",
                        "run_mcp_tests.step_exception",
                        step_description=step.description,
                        server=step.server,
                        tool=step.tool,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )

            total = passed + failed
            results = {
                "all_passed": failed == 0 and total > 0,
                "total_tests": total,
                "passed": passed,
                "failed": failed,
                "failure_details": failure_details,
            }
            self._log(
                "INFO",
                "run_mcp_tests.complete",
                total_tests=total,
                passed=passed,
                failed=failed,
            )
            return results
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
        self._log(
            "INFO",
            "run_all.start",
            code_files=len(code_files),
            test_files=len(test_files),
            has_mcp_plan=bool(mcp_plan and mcp_plan.steps),
        )
        if test_files:
            unit_results = self.run(code_files, test_files)
        else:
            unit_results = _empty_results()

        if mcp_plan and mcp_plan.steps:
            mcp_results = self.run_mcp_tests(mcp_plan, project_dir)
            total = unit_results["total_tests"] + mcp_results["total_tests"]
            failed = unit_results["failed"] + mcp_results["failed"]
            merged = {
                "all_passed": failed == 0 and total > 0,
                "total_tests": total,
                "passed": unit_results["passed"] + mcp_results["passed"],
                "failed": failed,
                "failure_details": (
                    unit_results["failure_details"]
                    + mcp_results["failure_details"]
                ),
            }
            self._log(
                "INFO",
                "run_all.complete",
                total_tests=merged["total_tests"],
                failed=merged["failed"],
                all_passed=merged["all_passed"],
            )
            return merged

        self._log(
            "INFO",
            "run_all.complete",
            total_tests=unit_results["total_tests"],
            failed=unit_results["failed"],
            all_passed=unit_results["all_passed"],
        )
        return unit_results


def _empty_results() -> dict:
    return {
        "all_passed": True,
        "total_tests": 0,
        "passed": 0,
        "failed": 0,
        "failure_details": [],
    }
