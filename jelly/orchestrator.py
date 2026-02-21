from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console

from jelly.agents.programmer import Programmer
from jelly.agents.test_designer import TestDesigner
from jelly.agents.test_executor import TestExecutor
from jelly.config import Config
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
) -> None:
    total = 5
    event = ProgressEvent(step, total, title, status, detail, iteration)

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
) -> dict:
    """Run the full generate-test-fix loop.

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
    requirements = read_file(requirements_path)
    signatures = extract_signatures(requirements)

    if on_progress is None:
        console.rule("[bold blue]Jelly — Multi-Agent Coding System")

    # Step 1: Design tests
    _emit(on_progress, 1, "Designing tests from requirements...", "running", "")
    test_designer = TestDesigner(config)
    design = test_designer.design_tests(requirements, signatures)
    test_files = design.unit_test_files
    mcp_plan = design.mcp_test_plan
    detail = f"Generated {len(test_files)} test file(s)"
    if mcp_plan.steps:
        detail += (
            f", MCP plan: {len(mcp_plan.steps)} step(s) "
            f"across {len(mcp_plan.servers)} server(s)"
        )
    _emit(on_progress, 1, "Designing tests from requirements...", "complete", detail)

    # Step 2: Generate code
    _emit(on_progress, 2, "Generating code from requirements...", "running", "")
    programmer = Programmer(config)
    code_files = programmer.generate(requirements)
    _emit(
        on_progress, 2, "Generating code from requirements...", "complete",
        f"Generated {len(code_files)} source file(s)",
    )

    # Step 3: Adapt tests
    _emit(on_progress, 3, "Adapting tests to match generated code...", "running", "")
    test_files = test_designer.adapt_tests(code_files, test_files)
    _emit(
        on_progress, 3, "Adapting tests to match generated code...", "complete",
        f"Adapted {len(test_files)} test file(s)",
    )

    # Step 4: Test and iterate
    _emit(on_progress, 4, "Testing and iterating...", "running", "")
    executor = TestExecutor(config)
    results: dict = {}

    for i in range(1, config.max_fix_iterations + 1):
        results = executor.run_all(code_files, test_files, mcp_plan, project_dir)

        if results["all_passed"]:
            _emit(
                on_progress, 4, "Testing and iterating...", "complete",
                f"All {results['total_tests']} tests passed (iteration {i})",
                iteration=i,
            )
            break

        msg = f"Iteration {i}: {results['failed']}/{results['total_tests']} failed"
        _emit(on_progress, 4, "Testing and iterating...", "running", msg, iteration=i)

        if i < config.max_fix_iterations:
            feedback = executor.format_feedback(results)
            code_files = programmer.refine(requirements, code_files, feedback, i)
            test_files = test_designer.adapt_tests(code_files, test_files)
        else:
            _emit(
                on_progress, 4, "Testing and iterating...", "failed",
                f"Max iterations reached — {results['failed']} test(s) still failing",
                iteration=i,
            )

    # Step 5: Write outputs
    _emit(on_progress, 5, f"Writing output to {project_dir}...", "running", "")
    write_files(f"{project_dir}/src", code_files)
    write_files(f"{project_dir}/tests", test_files)
    _emit(
        on_progress, 5, f"Writing output to {project_dir}...", "complete",
        f"Wrote {len(code_files)} source + {len(test_files)} test file(s)",
    )

    if on_progress is None:
        console.rule("[bold blue]Complete")

    return results
