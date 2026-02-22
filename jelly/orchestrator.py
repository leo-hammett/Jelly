from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

from jelly.agents.programmer import Programmer
from jelly.agents.test_designer import TestDesigner
from jelly.agents.test_executor import TestExecutor
from jelly.capability import assess_capability
from jelly.config import Config
from jelly.mcp import MCPBootstrapResult, bootstrap_servers
from jelly.mcp_sidecar_manager import MCPSidecarManager
from jelly.pregnancy import delegate_to_child_builder
from jelly.run_logging import RunLogger
from jelly.utils import extract_signatures, read_file, write_files

console = Console()


@dataclass
class ProgressEvent:
    """A structured progress update emitted during pipeline execution."""

    step: int
    total_steps: int
    title: str
    status: str  # "running" | "complete" | "failed"
    detail: str
    iteration: int = 0
    meta: dict[str, object] = field(default_factory=dict)


ProgressCallback = Callable[[ProgressEvent], None] | None


def _emit(
    callback: ProgressCallback,
    step: int,
    title: str,
    status: str,
    detail: str,
    iteration: int = 0,
    total_steps: int = 5,
    meta: dict[str, object] | None = None,
) -> None:
    event = ProgressEvent(
        step,
        total_steps,
        title,
        status,
        detail,
        iteration,
        meta or {},
    )

    if callback is not None:
        callback(event)
        return

    if status == "running":
        if detail:
            console.print(f"  {detail}")
        else:
            console.print(f"\n[bold cyan]Step {step}:[/] {title}")
    elif status == "complete":
        console.print(f"  {detail}")
    elif status == "failed":
        console.print(f"  [bold red]{detail}[/]")


def run_task(
    requirements_path: str,
    project_dir: str,
    on_progress: ProgressCallback = None,
    pregnancy_depth: int | None = None,
    pregnancy_signatures: list[str] | None = None,
) -> dict:
    """Run the full generate-test-fix loop.

    Step 0 (optional): capability gate + child delegation.
    1. Read requirements and extract function signatures.
    2. Generate tests ONCE (from requirements only — Test Designer never sees code).
    3. Generate code from requirements.
    4. Adapt tests so imports/references match the actual generated code.
    5. Run tests; if failures, feed errors back to Programmer (max 3 iterations).
       Re-adapt tests after each refinement to stay in sync.
    6. Write final code and test files to project_dir.

    Args:
        requirements_path: Path to the requirements markdown file.
        project_dir: Output directory for generated src/ and tests/.
        on_progress: Optional callback for structured progress events.

    Returns:
        Final structured test results dict.
    """
    config = Config()
    depth = max(0, pregnancy_depth or 0)
    seen_signatures = list(pregnancy_signatures or [])
    total_steps = 6 if config.enable_step2_pregnancy else 5
    abs_requirements = str(Path(requirements_path).resolve())
    abs_project_dir = str(Path(project_dir).resolve())
    logger = RunLogger.create(
        config.log_dir,
        config.log_level,
        requirements_path=abs_requirements,
        project_dir=abs_project_dir,
    )
    logger.event(
        "INFO",
        "orchestrator",
        "run.start",
        max_fix_iterations=config.max_fix_iterations,
        enable_step2_pregnancy=config.enable_step2_pregnancy,
        pregnancy_depth=depth,
        pregnancy_signature_count=len(seen_signatures),
        pregnancy_max_depth=config.pregnancy_max_depth,
    )
    sidecar_manager = MCPSidecarManager(config, project_dir, logger=logger)

    requirements = read_file(requirements_path)
    signatures = extract_signatures(requirements)

    if on_progress is None:
        console.rule("[bold blue]Jelly — Multi-Agent Coding System")
        console.print(f"[dim]Run log: {logger.log_file}[/dim]")

    if config.enable_step2_pregnancy:
        _emit(
            on_progress,
            0,
            "Checking build capability...",
            "running",
            "",
            total_steps=total_steps,
        )
        _emit(
            on_progress,
            0,
            "Checking build capability...",
            "running",
            "Running deterministic preflight checks and capability assessment.",
            total_steps=total_steps,
        )
        decision = assess_capability(
            requirements=requirements,
            requirements_path=requirements_path,
            project_dir=project_dir,
            config=config,
            depth=depth,
            logger=logger,
        )
        _emit(
            on_progress,
            0,
            "Checking build capability...",
            "running",
            _mcp_baseline_summary(
                decision.mcp_baseline_status,
                require_baseline=config.require_mcp_baseline,
            ),
            total_steps=total_steps,
            meta={"kind": "mcp_baseline"},
        )
        logger.event(
            "INFO",
            "orchestrator",
            "capability.decision",
            capable=decision.capable,
            confidence=decision.confidence,
            missing_capabilities=decision.missing_capabilities,
            depth=depth,
        )
        if not decision.capable:
            missing = ", ".join(decision.missing_capabilities[:3]) or "unspecified gap"
            _emit(
                on_progress,
                0,
                "Checking build capability...",
                "running",
                (
                    f"Capability gate requested child delegation "
                    f"(confidence {decision.confidence:.2f}; missing: {missing})."
                ),
                total_steps=total_steps,
                meta={"kind": "capability_decision"},
            )
            child_results = delegate_to_child_builder(
                requirements_path=requirements_path,
                project_dir=project_dir,
                capability_decision=decision,
                config=config,
                depth=depth,
                seen_signatures=seen_signatures,
                logger=logger,
            )
            child_results["capability_decision"] = decision.to_dict()
            if child_results.get("all_passed"):
                _emit(
                    on_progress,
                    0,
                    "Checking build capability...",
                    "complete",
                    "Delegated to child builder successfully and received passing results.",
                    total_steps=total_steps,
                )
            else:
                _emit(
                    on_progress,
                    0,
                    "Checking build capability...",
                    "failed",
                    "Delegation to child builder failed to produce a passing result.",
                    total_steps=total_steps,
                )
            logger.event(
                "INFO",
                "orchestrator",
                "run.complete",
                all_passed=child_results.get("all_passed", False),
                total_tests=child_results.get("total_tests", 0),
                failed=child_results.get("failed", 0),
                delegated_to_child=child_results.get("delegated_to_child", False),
            )
            sidecar_manager.stop_all()
            child_results["run_log_file"] = str(logger.log_file)
            return child_results
        _emit(
            on_progress,
            0,
            "Checking build capability...",
            "complete",
            (
                "Capability check passed "
                f"(confidence {decision.confidence:.2f}). "
                "Proceeding with local design/generate/test loop."
            ),
            total_steps=total_steps,
            meta={"kind": "capability_decision"},
        )

    mcp_bootstrap = MCPBootstrapResult()
    bootstrap_servers_for_design = None
    if config.mcp_bootstrap_enabled:
        _emit(
            on_progress,
            1,
            "Designing tests from requirements...",
            "running",
            "Bootstrapping configured MCP servers for this run.",
            total_steps=total_steps,
            meta={"kind": "mcp_bootstrap"},
        )
        with logger.timed("orchestrator", "mcp_bootstrap"):
            mcp_bootstrap = bootstrap_servers(config, project_dir, logger=logger)
        _emit(
            on_progress,
            1,
            "Designing tests from requirements...",
            "running",
            _mcp_bootstrap_summary(mcp_bootstrap),
            total_steps=total_steps,
            meta={"kind": "mcp_bootstrap"},
        )
        bootstrap_servers_for_design = list(mcp_bootstrap.available_servers)
        behavior = config.mcp_unavailable_behavior.strip().lower()
        if mcp_bootstrap.unavailable and behavior == "fail_closed":
            failure_detail = (
                "Configured MCP bootstrap has unavailable servers and "
                "fail-closed policy is enabled."
            )
            _emit(
                on_progress,
                1,
                "Designing tests from requirements...",
                "failed",
                failure_detail,
                total_steps=total_steps,
                meta={"kind": "mcp_bootstrap"},
            )
            results = _mcp_bootstrap_failure_results(mcp_bootstrap)
            logger.event(
                "WARNING",
                "orchestrator",
                "run.failed_mcp_bootstrap",
                unavailable=mcp_bootstrap.unavailable,
                behavior=behavior,
            )
            logger.event(
                "INFO",
                "orchestrator",
                "run.complete",
                all_passed=False,
                total_tests=results.get("total_tests", 0),
                failed=results.get("failed", 0),
            )
            sidecar_manager.stop_all()
            results["mcp_bootstrap"] = mcp_bootstrap.to_status()
            results["run_log_file"] = str(logger.log_file)
            return results
        if mcp_bootstrap.unavailable and behavior == "unit_only_fallback":
            bootstrap_servers_for_design = []
            _emit(
                on_progress,
                1,
                "Designing tests from requirements...",
                "running",
                "MCP bootstrap unavailable; policy switched run to unit-tests-only mode.",
                total_steps=total_steps,
                meta={"kind": "mcp_bootstrap"},
            )

    # Step 1 + Step 2: design tests and generate code in parallel.
    test_designer = TestDesigner(config, logger=logger)
    programmer = Programmer(config)
    _emit(
        on_progress, 1, "Designing tests from requirements...", "running", "",
        total_steps=total_steps,
    )
    _emit(
        on_progress,
        1,
        "Designing tests from requirements...",
        "running",
        (
            f"Extracted {len(signatures)} signature(s); "
            "building unit tests and optional MCP test plan."
        ),
        total_steps=total_steps,
    )
    logger.event(
        "INFO",
        "orchestrator",
        "step.start",
        step=1,
        title="Design tests",
    )
    _emit(
        on_progress, 2, "Generating code from requirements...", "running", "",
        total_steps=total_steps,
    )
    _emit(
        on_progress,
        2,
        "Generating code from requirements...",
        "running",
        "Programmer is drafting source files from requirements.",
        total_steps=total_steps,
    )
    logger.event(
        "INFO",
        "orchestrator",
        "step.start",
        step=2,
        title="Generate code",
    )

    def _design_tests_job():
        with logger.timed("orchestrator", "design_tests"):
            return test_designer.design_tests(
                requirements,
                signatures,
                project_dir,
                preinstalled_servers=bootstrap_servers_for_design,
            )

    def _generate_code_job():
        with logger.timed("orchestrator", "generate_code"):
            return programmer.generate(requirements)

    with ThreadPoolExecutor(max_workers=2) as pool:
        design_future = pool.submit(_design_tests_job)
        code_future = pool.submit(_generate_code_job)
        design = design_future.result()
        code_files = code_future.result()

    test_files = design.unit_test_files
    mcp_plan = design.mcp_test_plan
    detail = f"Generated {len(test_files)} test file(s)"
    if mcp_plan.steps:
        detail += (
            f", MCP plan: {len(mcp_plan.steps)} step(s) "
            f"across {len(mcp_plan.servers)} server(s)"
        )
        _emit(
            on_progress,
            1,
            "Designing tests from requirements...",
            "running",
            (
                f"MCP plan is active: {len(mcp_plan.steps)} step(s), "
                f"{len(mcp_plan.servers)} server(s)."
            ),
            total_steps=total_steps,
            meta={"kind": "mcp_plan"},
        )
    else:
        detail += ", MCP plan: none (unit tests only)"
        _emit(
            on_progress,
            1,
            "Designing tests from requirements...",
            "running",
            "No MCP steps selected; continuing with unit tests only.",
            total_steps=total_steps,
            meta={"kind": "mcp_plan"},
        )
    _emit(
        on_progress, 1, "Designing tests from requirements...", "complete", detail,
        total_steps=total_steps,
    )
    logger.event(
        "INFO",
        "orchestrator",
        "step.complete",
        step=1,
        title="Design tests",
        test_files=len(test_files),
        mcp_servers=len(mcp_plan.servers),
        mcp_steps=len(mcp_plan.steps),
    )
    _emit(
        on_progress, 2, "Generating code from requirements...", "complete",
        f"Generated {len(code_files)} source file(s)",
        total_steps=total_steps,
    )
    logger.event(
        "INFO",
        "orchestrator",
        "step.complete",
        step=2,
        title="Generate code",
        code_files=len(code_files),
    )

    # Step 3: Adapt tests
    _emit(
        on_progress, 3, "Adapting tests to match generated code...", "running", "",
        total_steps=total_steps,
    )
    _emit(
        on_progress,
        3,
        "Adapting tests to match generated code...",
        "running",
        "Aligning imports and symbols so tests target generated code correctly.",
        total_steps=total_steps,
    )
    logger.event(
        "INFO",
        "orchestrator",
        "step.start",
        step=3,
        title="Adapt tests",
    )
    with logger.timed("orchestrator", "adapt_tests"):
        test_files = test_designer.adapt_tests(code_files, test_files)
    _emit(
        on_progress, 3, "Adapting tests to match generated code...", "complete",
        f"Adapted {len(test_files)} test file(s)",
        total_steps=total_steps,
    )
    logger.event(
        "INFO",
        "orchestrator",
        "step.complete",
        step=3,
        title="Adapt tests",
        test_files=len(test_files),
    )

    # Step 4: Test and iterate
    _emit(
        on_progress, 4, "Testing and iterating...", "running", "",
        total_steps=total_steps,
    )
    _emit(
        on_progress,
        4,
        "Testing and iterating...",
        "running",
        "Executing unit tests and MCP steps (when configured).",
        total_steps=total_steps,
    )
    if mcp_plan.steps:
        _emit(
            on_progress,
            4,
            "Testing and iterating...",
            "running",
            (
                f"MCP execution target: {len(mcp_plan.steps)} step(s) "
                f"across {len(mcp_plan.servers)} server(s)."
            ),
            total_steps=total_steps,
            meta={"kind": "mcp_plan"},
        )
    logger.event(
        "INFO",
        "orchestrator",
        "step.start",
        step=4,
        title="Test & iterate",
    )
    executor = TestExecutor(config, logger=logger, sidecar_manager=sidecar_manager)
    results: dict = {}

    for i in range(1, config.max_fix_iterations + 1):
        _emit(
            on_progress,
            4,
            "Testing and iterating...",
            "running",
            f"Iteration {i}: running unit tests and MCP checks.",
            iteration=i,
            total_steps=total_steps,
        )
        logger.event(
            "INFO",
            "orchestrator",
            "iteration.start",
            iteration=i,
            code_files=len(code_files),
            test_files=len(test_files),
            mcp_steps=len(mcp_plan.steps) if mcp_plan else 0,
        )
        results = executor.run_all(code_files, test_files, mcp_plan, project_dir)
        logger.event(
            "INFO",
            "orchestrator",
            "iteration.results",
            iteration=i,
            all_passed=results.get("all_passed"),
            total_tests=results.get("total_tests"),
            passed=results.get("passed"),
            failed=results.get("failed"),
        )

        if results["all_passed"]:
            mcp_detail = _mcp_results_summary(results)
            complete_detail = f"All {results['total_tests']} tests passed (iteration {i})"
            if mcp_detail:
                complete_detail = f"{complete_detail}. {mcp_detail}"
            _emit(
                on_progress, 4, "Testing and iterating...", "complete",
                complete_detail,
                iteration=i,
                total_steps=total_steps,
            )
            logger.event(
                "INFO",
                "orchestrator",
                "step.complete",
                step=4,
                title="Test & iterate",
                iteration=i,
                total_tests=results["total_tests"],
                failed=results["failed"],
            )
            break

        msg = f"Iteration {i}: {results['failed']}/{results['total_tests']} failed"
        mcp_detail = _mcp_results_summary(results)
        if mcp_detail:
            msg = f"{msg}. {mcp_detail}"
        _emit(
            on_progress, 4, "Testing and iterating...", "running", msg, iteration=i,
            total_steps=total_steps,
        )

        if i < config.max_fix_iterations:
            _emit(
                on_progress,
                4,
                "Testing and iterating...",
                "running",
                "Applying failure feedback to code, then re-adapting tests.",
                iteration=i,
                total_steps=total_steps,
            )
            feedback = executor.format_feedback(results)
            logger.event(
                "INFO",
                "orchestrator",
                "refine.start",
                iteration=i,
                feedback_length=len(feedback),
            )
            previous_code_files = dict(code_files)
            code_files = programmer.refine(requirements, code_files, feedback, i)
            should_adapt, adapt_reason = _should_readapt_tests(
                results,
                previous_code_files,
                code_files,
            )
            if should_adapt:
                test_files = test_designer.adapt_tests(code_files, test_files)
            else:
                _emit(
                    on_progress,
                    4,
                    "Testing and iterating...",
                    "running",
                    (
                        "Skipping test adaptation this iteration; failures look "
                        "MCP/runtime-only."
                    ),
                    iteration=i,
                    total_steps=total_steps,
                )
            logger.event(
                "INFO",
                "orchestrator",
                "refine.complete",
                iteration=i,
                code_files=len(code_files),
                test_files=len(test_files),
                adapt_tests_rerun=should_adapt,
                adapt_tests_reason=adapt_reason,
            )
        else:
            failed_detail = (
                f"Max iterations reached — {results['failed']} test(s) still failing"
            )
            if mcp_detail:
                failed_detail = f"{failed_detail}. {mcp_detail}"
            _emit(
                on_progress, 4, "Testing and iterating...", "failed",
                failed_detail,
                iteration=i,
                total_steps=total_steps,
            )
            logger.event(
                "WARNING",
                "orchestrator",
                "step.failed",
                step=4,
                title="Test & iterate",
                iteration=i,
                failed=results["failed"],
                total_tests=results["total_tests"],
            )

    # Step 5: Write outputs
    _emit(
        on_progress, 5, f"Writing output to {project_dir}...", "running", "",
        total_steps=total_steps,
    )
    _emit(
        on_progress,
        5,
        f"Writing output to {project_dir}...",
        "running",
        "Persisting final source and test files to the output workspace.",
        total_steps=total_steps,
    )
    logger.event(
        "INFO",
        "orchestrator",
        "step.start",
        step=5,
        title="Write output",
        clean_before_write=config.clean_output_before_write,
    )
    with logger.timed("orchestrator", "write_outputs"):
        write_files(
            f"{project_dir}/src",
            code_files,
            clean=config.clean_output_before_write,
        )
        write_files(
            f"{project_dir}/tests",
            test_files,
            clean=config.clean_output_before_write,
        )
    _emit(
        on_progress, 5, f"Writing output to {project_dir}...", "complete",
        f"Wrote {len(code_files)} source + {len(test_files)} test file(s)",
        total_steps=total_steps,
    )
    logger.event(
        "INFO",
        "orchestrator",
        "step.complete",
        step=5,
        title="Write output",
        code_files=len(code_files),
        test_files=len(test_files),
    )

    if on_progress is None:
        console.rule("[bold blue]Complete")

    logger.event(
        "INFO",
        "orchestrator",
        "run.complete",
        all_passed=results.get("all_passed", False),
        total_tests=results.get("total_tests", 0),
        failed=results.get("failed", 0),
    )
    sidecar_manager.stop_all()
    results["mcp_bootstrap"] = mcp_bootstrap.to_status()
    results["run_log_file"] = str(logger.log_file)
    return results


def _mcp_baseline_summary(
    baseline: dict[str, object],
    *,
    require_baseline: bool,
) -> str:
    mode = "required" if require_baseline else "diagnostic"
    fs = baseline.get("filesystem", {}) if isinstance(baseline, dict) else {}
    browser = baseline.get("browser", {}) if isinstance(baseline, dict) else {}
    fs_state = (
        "available"
        if isinstance(fs, dict) and bool(fs.get("available"))
        else "unavailable"
    )
    browser_state = (
        "available"
        if isinstance(browser, dict) and bool(browser.get("available"))
        else "unavailable"
    )
    return (
        "MCP baseline "
        f"({mode}): filesystem={fs_state}, browser={browser_state}."
    )


def _mcp_bootstrap_summary(result: MCPBootstrapResult) -> str:
    requested = len(result.requested_servers)
    available = len(result.available_servers)
    unavailable = len(result.unavailable)
    if requested == 0:
        return "MCP bootstrap: no preset servers configured."
    detail = (
        f"MCP bootstrap: {available}/{requested} server(s) available; "
        f"{unavailable} unavailable."
    )
    if result.unavailable:
        names = ", ".join(sorted(result.unavailable.keys())[:3])
        detail = f"{detail} Unavailable: {names}."
    return detail


def _mcp_bootstrap_failure_results(result: MCPBootstrapResult) -> dict:
    unavailable_detail = ", ".join(
        f"{name} ({reason})" for name, reason in sorted(result.unavailable.items())
    )
    return {
        "all_passed": False,
        "total_tests": 1,
        "passed": 0,
        "failed": 1,
        "failure_details": [
            {
                "test_name": "(mcp bootstrap)",
                "error_type": "MCPBootstrapUnavailable",
                "error_message": (
                    "Configured MCP servers are unavailable: "
                    f"{unavailable_detail or 'unspecified'}"
                ),
                "traceback": "",
            }
        ],
        "mcp_summary": {
            "plan_present": False,
            "servers_requested": len(result.requested_servers),
            "servers_available": len(result.available_servers),
            "servers_started": 0,
            "servers_failed": len(result.unavailable),
            "failed_servers": sorted(result.unavailable.keys()),
            "steps_total": 0,
            "steps_passed": 0,
            "steps_failed": 0,
            "failure_examples": [],
        },
    }


def _mcp_results_summary(results: dict) -> str:
    summary = results.get("mcp_summary")
    if not isinstance(summary, dict):
        return ""

    plan_present = bool(summary.get("plan_present"))
    steps_total = int(summary.get("steps_total", 0) or 0)
    servers_available = int(summary.get("servers_available", 0) or 0)
    servers_requested = int(summary.get("servers_requested", 0) or 0)
    if steps_total <= 0:
        if plan_present:
            return (
                "MCP plan present, but no executable MCP steps were run. "
                f"Availability: {servers_available}/{servers_requested} server(s)."
            )
        return ""

    steps_passed = int(summary.get("steps_passed", 0) or 0)
    servers_started = int(summary.get("servers_started", 0) or 0)
    detail = (
        "MCP results: "
        f"{steps_passed}/{steps_total} step(s) passed, "
        f"{servers_started}/{servers_available or servers_requested} server(s) started "
        f"(available {servers_available}/{servers_requested})."
    )
    dynamic_launched = int(summary.get("dynamic_launched", 0) or 0)
    if dynamic_launched > 0:
        dynamic_installed = int(summary.get("dynamic_installed", 0) or 0)
        dynamic_reused = int(summary.get("dynamic_reused", 0) or 0)
        dynamic_failed = int(summary.get("dynamic_failed", 0) or 0)
        detail = (
            f"{detail} Dynamic sidecars: installed {dynamic_installed}, "
            f"launched {dynamic_launched}, reused {dynamic_reused}, failed {dynamic_failed}."
        )
        launch_modes = summary.get("dynamic_launch_modes", {})
        if isinstance(launch_modes, dict) and launch_modes:
            modes_text = ", ".join(
                f"{name}={count}"
                for name, count in sorted(launch_modes.items(), key=lambda item: item[0])
            )
            detail = f"{detail} Launch modes: {modes_text}."
    return detail


_ADAPT_RELEVANT_ERROR_TYPES = {
    "importerror",
    "modulenotfounderror",
    "nameerror",
    "attributeerror",
    "syntaxerror",
    "indentationerror",
}
_ADAPT_RELEVANT_TEXT_FRAGMENTS = (
    "no module named",
    "cannot import name",
    "importerror",
    "nameerror",
    "attributeerror",
    "has no attribute",
    "is not defined",
    "found no collectors",
    "fixture",
    "syntaxerror",
    "indentationerror",
)


def _should_readapt_tests(
    results: dict,
    previous_code_files: dict[str, str],
    current_code_files: dict[str, str],
) -> tuple[bool, str]:
    if _code_module_structure_changed(previous_code_files, current_code_files):
        return True, "code_structure_changed"

    failure_details = results.get("failure_details", [])
    if not isinstance(failure_details, list):
        return False, "no_failure_details"

    for failure in failure_details:
        if _failure_requires_test_adaptation(failure):
            return True, "import_symbol_or_test_structure_failure"
    return False, "mcp_or_runtime_only"


def _code_module_structure_changed(
    previous_code_files: dict[str, str],
    current_code_files: dict[str, str],
) -> bool:
    return sorted(previous_code_files.keys()) != sorted(current_code_files.keys())


def _failure_requires_test_adaptation(failure: object) -> bool:
    if not isinstance(failure, dict):
        return False
    error_type = str(failure.get("error_type", "")).strip().lower()
    if error_type in _ADAPT_RELEVANT_ERROR_TYPES:
        return True
    text_parts = [
        str(failure.get("test_name", "")),
        str(failure.get("error_message", "")),
        str(failure.get("traceback", "")),
    ]
    merged = " ".join(text_parts).lower()
    return any(fragment in merged for fragment in _ADAPT_RELEVANT_TEXT_FRAGMENTS)
