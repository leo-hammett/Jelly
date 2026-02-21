from jelly.config import Config
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
