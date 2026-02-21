from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from jelly.agents.programmer import Programmer
from jelly.agents.test_designer import TestDesigner
from jelly.agents.test_executor import TestExecutor
from jelly.capability import assess_capability
from jelly.config import Config
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


ProgressCallback = Callable[[ProgressEvent], None] | None


def _emit(
    callback: ProgressCallback,
    step: int,
    title: str,
    status: str,
    detail: str,
    iteration: int = 0,
    total_steps: int = 5,
) -> None:
    event = ProgressEvent(step, total_steps, title, status, detail, iteration)

    if callback is not None:
        callback(event)
        return

    if status == "running":
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
        decision = assess_capability(
            requirements=requirements,
            requirements_path=requirements_path,
            project_dir=project_dir,
            config=config,
            depth=depth,
            logger=logger,
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
                    "Delegated to child builder successfully.",
                    total_steps=total_steps,
                )
            else:
                _emit(
                    on_progress,
                    0,
                    "Checking build capability...",
                    "failed",
                    "Delegation to child builder failed.",
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
            child_results["run_log_file"] = str(logger.log_file)
            return child_results
        _emit(
            on_progress,
            0,
            "Checking build capability...",
            "complete",
            f"Capability check passed (confidence {decision.confidence:.2f}).",
            total_steps=total_steps,
        )

    # Step 1: Design tests
    _emit(
        on_progress, 1, "Designing tests from requirements...", "running", "",
        total_steps=total_steps,
    )
    logger.event(
        "INFO",
        "orchestrator",
        "step.start",
        step=1,
        title="Design tests",
    )
    test_designer = TestDesigner(config, logger=logger)
    with logger.timed("orchestrator", "design_tests"):
        design = test_designer.design_tests(requirements, signatures, project_dir)
    test_files = design.unit_test_files
    mcp_plan = design.mcp_test_plan
    detail = f"Generated {len(test_files)} test file(s)"
    if mcp_plan.steps:
        detail += (
            f", MCP plan: {len(mcp_plan.steps)} step(s) "
            f"across {len(mcp_plan.servers)} server(s)"
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

    # Step 2: Generate code
    _emit(
        on_progress, 2, "Generating code from requirements...", "running", "",
        total_steps=total_steps,
    )
    logger.event(
        "INFO",
        "orchestrator",
        "step.start",
        step=2,
        title="Generate code",
    )
    programmer = Programmer(config)
    with logger.timed("orchestrator", "generate_code"):
        code_files = programmer.generate(requirements)
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
    logger.event(
        "INFO",
        "orchestrator",
        "step.start",
        step=4,
        title="Test & iterate",
    )
    executor = TestExecutor(config, logger=logger)
    results: dict = {}

    for i in range(1, config.max_fix_iterations + 1):
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
            _emit(
                on_progress, 4, "Testing and iterating...", "complete",
                f"All {results['total_tests']} tests passed (iteration {i})",
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
        _emit(
            on_progress, 4, "Testing and iterating...", "running", msg, iteration=i,
            total_steps=total_steps,
        )

        if i < config.max_fix_iterations:
            feedback = executor.format_feedback(results)
            logger.event(
                "INFO",
                "orchestrator",
                "refine.start",
                iteration=i,
                feedback_length=len(feedback),
            )
            code_files = programmer.refine(requirements, code_files, feedback, i)
            test_files = test_designer.adapt_tests(code_files, test_files)
            logger.event(
                "INFO",
                "orchestrator",
                "refine.complete",
                iteration=i,
                code_files=len(code_files),
                test_files=len(test_files),
            )
        else:
            _emit(
                on_progress, 4, "Testing and iterating...", "failed",
                f"Max iterations reached — {results['failed']} test(s) still failing",
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
    results["run_log_file"] = str(logger.log_file)
    return results
