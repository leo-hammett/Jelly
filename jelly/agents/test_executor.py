from pathlib import Path
import json

from jelly.config import Config
from jelly.mcp import (
    MCPTestPlan,
    can_lazy_provision,
    call_tool_for_server,
    start_server_for_transport,
    stop_server_for_transport,
)
from jelly.mcp_sidecar_manager import MCPSidecarManager
from jelly.run_logging import RunLogger
from jelly.sandbox.runner import run_tests


class TestExecutor:
    """Runs tests and produces structured feedback.

    Mostly Python logic, minimal LLM usage.
    """

    def __init__(
        self,
        config: Config,
        logger: RunLogger | None = None,
        sidecar_manager: MCPSidecarManager | None = None,
    ) -> None:
        """Initialize with config (for timeout settings)."""
        self.config = config
        self.logger = logger
        self.sidecar_manager = sidecar_manager
        # MCP steps that failed once in this run are quarantined on later iterations.
        self._quarantined_mcp_steps: set[str] = set()
        # Entire MCP servers that failed once in this run are quarantined too.
        self._quarantined_mcp_servers: set[str] = set()

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
            results = _empty_results()
            results["mcp_summary"] = {
                "plan_present": False,
                "servers_requested": len(plan.servers),
                "servers_available": len(plan.servers),
                "servers_started": 0,
                "servers_failed": 0,
                "failed_servers": [],
                "steps_total": 0,
                "steps_passed": 0,
                "steps_failed": 0,
                "failure_examples": [],
                "plan_reason": plan.reason,
                "dynamic_installed": 0,
                "dynamic_launched": 0,
                "dynamic_reused": 0,
                "dynamic_failed": 0,
                "dynamic_failed_servers": [],
                "dynamic_launch_modes": {},
                "dynamic_failed_install_servers": [],
                "dynamic_failed_install_packages": [],
                "servers_quarantined": len(self._quarantined_mcp_servers),
                "quarantined_servers": sorted(self._quarantined_mcp_servers),
            }
            return results

        procs: dict[str, object] = {}
        startup_errors: dict[str, Exception] = {}
        servers_by_name = {server.name: server for server in plan.servers}
        dynamic_provisioned: set[str] = set()
        dynamic_reused: set[str] = set()
        dynamic_call_seen: set[str] = set()
        dynamic_failed: set[str] = set()
        self._log(
            "INFO",
            "run_mcp_tests.start",
            servers=len(plan.servers),
            steps=len(plan.steps),
            project_dir=str(Path(project_dir).resolve()),
        )
        try:
            for server in plan.servers:
                if server.name in self._quarantined_mcp_servers:
                    self._log(
                        "INFO",
                        "run_mcp_tests.server_start_skipped_quarantined",
                        server=server.name,
                    )
                    continue
                if can_lazy_provision(server) and self.sidecar_manager is not None:
                    self._log(
                        "INFO",
                        "run_mcp_tests.server_deferred_provision",
                        server=server.name,
                    )
                    continue
                try:
                    self._log(
                        "INFO",
                        "run_mcp_tests.server_starting",
                        server=server.name,
                        transport=server.transport,
                        command=server.command,
                        args=server.args,
                        endpoint=server.endpoint,
                    )
                    procs[server.name] = start_server_for_transport(
                        server,
                        startup_wait=float(self.config.mcp_test_timeout),
                        request_timeout=float(self.config.mcp_test_timeout),
                        logger=self.logger,
                        allow_node_stdio=(
                            self.config.mcp_transport_mode.strip().lower()
                            == "allow_node_stdio"
                        ),
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
            skipped_quarantined = 0
            failure_details: list[dict] = []

            for step in plan.steps:
                if step.server in self._quarantined_mcp_servers:
                    skipped_quarantined += 1
                    passed += 1
                    self._log(
                        "INFO",
                        "run_mcp_tests.server_quarantined_skip",
                        step_description=step.description,
                        server=step.server,
                        tool=step.tool,
                    )
                    continue
                step_key = self._step_key(step)
                if step_key in self._quarantined_mcp_steps:
                    skipped_quarantined += 1
                    passed += 1
                    self._log(
                        "INFO",
                        "run_mcp_tests.step_quarantined_skip",
                        step_description=step.description,
                        server=step.server,
                        tool=step.tool,
                    )
                    continue

                server = servers_by_name.get(step.server)
                if server is None:
                    failed += 1
                    self._quarantined_mcp_steps.add(step_key)
                    self._quarantined_mcp_servers.add(step.server)
                    failure_details.append({
                        "test_name": step.description,
                        "error_type": "ServerNotFound",
                        "error_message": (
                            f"No configured server named '{step.server}'"
                        ),
                        "traceback": "",
                    })
                    self._log(
                        "WARNING",
                        "run_mcp_tests.step_skipped_unknown_server",
                        step_description=step.description,
                        server=step.server,
                        available_servers=sorted(servers_by_name.keys()),
                    )
                    continue

                if step.server not in procs and can_lazy_provision(server):
                    if self.sidecar_manager is None:
                        dynamic_failed.add(step.server)
                        failed += 1
                        self._quarantined_mcp_steps.add(step_key)
                        self._quarantined_mcp_servers.add(step.server)
                        failure_details.append({
                            "test_name": step.description,
                            "error_type": "DynamicSidecarManagerMissing",
                            "error_message": (
                                f"Cannot provision dynamic sidecar '{step.server}' "
                                "without manager context."
                            ),
                            "traceback": "",
                        })
                        continue
                    try:
                        endpoint = self.sidecar_manager.ensure_running(server)
                        server.endpoint = endpoint
                        procs[server.name] = start_server_for_transport(
                            server,
                            startup_wait=float(self.config.mcp_test_timeout),
                            request_timeout=float(self.config.mcp_test_timeout),
                            logger=self.logger,
                            allow_node_stdio=(
                                self.config.mcp_transport_mode.strip().lower()
                                == "allow_node_stdio"
                            ),
                        )
                        dynamic_provisioned.add(server.name)
                        self._log(
                            "INFO",
                            "run_mcp_tests.server_provisioned",
                            server=server.name,
                            endpoint=endpoint,
                        )
                    except Exception as exc:
                        dynamic_failed.add(server.name)
                        failed += 1
                        self._quarantined_mcp_steps.add(step_key)
                        self._quarantined_mcp_servers.add(server.name)
                        failure_details.append({
                            "test_name": step.description,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc)[:500],
                            "traceback": "",
                        })
                        self._log(
                            "ERROR",
                            "run_mcp_tests.server_provision_failed",
                            server=server.name,
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                        )
                        continue

                proc = procs.get(step.server)
                if step.server not in procs:
                    failed += 1
                    self._quarantined_mcp_steps.add(step_key)
                    self._quarantined_mcp_servers.add(step.server)
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
                    just_provisioned = (
                        server.name in dynamic_provisioned
                        and server.name not in dynamic_call_seen
                    )
                    if server.name in dynamic_call_seen and server.name in dynamic_provisioned:
                        dynamic_reused.add(server.name)
                    attempt = 0
                    while True:
                        try:
                            result = call_tool_for_server(
                                server,
                                proc,
                                step.tool,
                                step.arguments,
                                timeout=float(self.config.mcp_test_timeout),
                                logger=self.logger,
                            )
                            break
                        except Exception:
                            if just_provisioned and attempt == 0:
                                attempt += 1
                                self._log(
                                    "WARNING",
                                    "run_mcp_tests.step_retry_after_provision",
                                    server=server.name,
                                    tool=step.tool,
                                    step_description=step.description,
                                )
                                continue
                            raise
                    dynamic_call_seen.add(server.name)
                    content_parts = result.get("content", [])
                    text = " ".join(
                        item.get("text", "")
                        for item in content_parts
                        if isinstance(item, dict) and item.get("type") == "text"
                    )
                    if step.expected and step.expected.lower() not in text.lower():
                        failed += 1
                        self._quarantined_mcp_steps.add(step_key)
                        self._quarantined_mcp_servers.add(step.server)
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
                    self._quarantined_mcp_steps.add(step_key)
                    self._quarantined_mcp_servers.add(step.server)
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
            startup_error_types = {
                name: type(exc).__name__
                for name, exc in startup_errors.items()
            }
            failure_examples = [
                f"{failure['test_name']}: {failure['error_type']}"
                for failure in failure_details[:3]
            ]
            manager_summary = self.sidecar_manager.summary() if self.sidecar_manager else {}
            all_dynamic_failed = set(dynamic_failed)
            for failed_name in manager_summary.get("dynamic_failed_servers", []):
                all_dynamic_failed.add(str(failed_name))
            results = {
                "all_passed": failed == 0 and total > 0,
                "total_tests": total,
                "passed": passed,
                "failed": failed,
                "failure_details": failure_details,
                "mcp_summary": {
                    "plan_present": True,
                    "servers_requested": len(plan.servers),
                    "servers_available": len(plan.servers),
                    "servers_started": len(procs),
                    "servers_failed": len(startup_errors),
                    "failed_servers": sorted(startup_errors.keys()),
                    "startup_error_types": startup_error_types,
                    "steps_total": len(plan.steps),
                    "steps_passed": passed,
                    "steps_failed": failed,
                    "steps_skipped_quarantined": skipped_quarantined,
                    "failure_examples": failure_examples,
                    "plan_reason": plan.reason,
                    "dynamic_installed": int(manager_summary.get("dynamic_installed", 0)),
                    "dynamic_launched": int(manager_summary.get("dynamic_launched", 0)),
                    "dynamic_reused": max(
                        len(dynamic_reused),
                        int(manager_summary.get("dynamic_reused", 0)),
                    ),
                    "dynamic_failed": len(all_dynamic_failed),
                    "dynamic_failed_servers": sorted(all_dynamic_failed),
                    "dynamic_launch_modes": dict(
                        manager_summary.get("dynamic_launch_modes", {})
                    ),
                    "dynamic_failed_install_servers": list(
                        manager_summary.get("dynamic_failed_install_servers", [])
                    ),
                    "dynamic_failed_install_packages": list(
                        manager_summary.get("dynamic_failed_install_packages", [])
                    ),
                    "servers_quarantined": len(self._quarantined_mcp_servers),
                    "quarantined_servers": sorted(self._quarantined_mcp_servers),
                },
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
            for server in plan.servers:
                stop_server_for_transport(
                    server,
                    procs.get(server.name),
                )

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
                "mcp_summary": mcp_results.get("mcp_summary", {}),
            }
            self._log(
                "INFO",
                "run_all.complete",
                total_tests=merged["total_tests"],
                failed=merged["failed"],
                all_passed=merged["all_passed"],
            )
            return merged

        unit_results["mcp_summary"] = {
            "plan_present": bool(mcp_plan),
            "servers_requested": len(mcp_plan.servers) if mcp_plan else 0,
            "servers_available": len(mcp_plan.servers) if mcp_plan else 0,
            "servers_started": 0,
            "servers_failed": 0,
            "failed_servers": [],
            "steps_total": len(mcp_plan.steps) if mcp_plan else 0,
            "steps_passed": 0,
            "steps_failed": 0,
            "steps_skipped_quarantined": 0,
            "failure_examples": [],
            "plan_reason": mcp_plan.reason if mcp_plan else "",
            "dynamic_installed": 0,
            "dynamic_launched": 0,
            "dynamic_reused": 0,
            "dynamic_failed": 0,
            "dynamic_failed_servers": [],
            "dynamic_launch_modes": {},
            "dynamic_failed_install_servers": [],
            "dynamic_failed_install_packages": [],
            "servers_quarantined": len(self._quarantined_mcp_servers),
            "quarantined_servers": sorted(self._quarantined_mcp_servers),
        }
        self._log(
            "INFO",
            "run_all.complete",
            total_tests=unit_results["total_tests"],
            failed=unit_results["failed"],
            all_passed=unit_results["all_passed"],
        )
        return unit_results

    @staticmethod
    def _step_key(step) -> str:
        arguments = {}
        if hasattr(step, "arguments") and isinstance(step.arguments, dict):
            arguments = step.arguments
        return json.dumps(
            {
                "description": getattr(step, "description", ""),
                "server": getattr(step, "server", ""),
                "tool": getattr(step, "tool", ""),
                "arguments": arguments,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def _empty_results() -> dict:
    return {
        "all_passed": True,
        "total_tests": 0,
        "passed": 0,
        "failed": 0,
        "failure_details": [],
    }
