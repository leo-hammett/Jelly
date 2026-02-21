from rich.console import Console

from jelly.agents.programmer import Programmer
from jelly.agents.test_designer import TestDesigner
from jelly.agents.test_executor import TestExecutor
from jelly.config import Config
from jelly.utils import extract_signatures, read_file, write_files

console = Console()


def run_task(requirements_path: str, project_dir: str) -> dict:
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

    Returns:
        Final structured test results dict.
    """
    config = Config()
    requirements = read_file(requirements_path)
    signatures = extract_signatures(requirements)

    console.rule("[bold blue]Jelly — Multi-Agent Coding System")

    # Step 1: Design tests (analyze reqs, install MCP tools, generate tests)
    console.print("\n[bold cyan]Step 1:[/] Designing tests from requirements...")
    test_designer = TestDesigner(config)
    design = test_designer.design_tests(requirements, signatures)
    test_files = design.unit_test_files
    mcp_plan = design.mcp_test_plan
    console.print(f"  Generated {len(test_files)} test file(s)")
    if mcp_plan.steps:
        console.print(
            f"  MCP test plan: {len(mcp_plan.steps)} step(s) across "
            f"{len(mcp_plan.servers)} server(s)"
        )

    # Step 2: Generate code
    console.print("\n[bold cyan]Step 2:[/] Generating code from requirements...")
    programmer = Programmer(config)
    code_files = programmer.generate(requirements)
    console.print(f"  Generated {len(code_files)} source file(s)")

    # Step 3: Adapt tests to match actual code
    console.print("\n[bold cyan]Step 3:[/] Adapting tests to match generated code...")
    test_files = test_designer.adapt_tests(code_files, test_files)
    console.print(f"  Adapted {len(test_files)} test file(s)")

    # Step 4: Test and iterate
    console.print("\n[bold cyan]Step 4:[/] Testing and iterating...\n")
    executor = TestExecutor(config)
    results: dict = {}

    for i in range(1, config.max_fix_iterations + 1):
        results = executor.run_all(code_files, test_files, mcp_plan, project_dir)

        if results["all_passed"]:
            console.print(
                f"  [bold green]✅ All {results['total_tests']} tests passed "
                f"(iteration {i})[/]"
            )
            break

        console.print(
            f"  [bold red]❌ Iteration {i}: "
            f"{results['failed']}/{results['total_tests']} failed[/]"
        )

        if i < config.max_fix_iterations:
            console.print("  Feeding errors back to Programmer...")
            feedback = executor.format_feedback(results)
            code_files = programmer.refine(requirements, code_files, feedback, i)
            console.print(f"  Refined {len(code_files)} source file(s)")
            console.print("  Re-adapting tests to refined code...")
            test_files = test_designer.adapt_tests(code_files, test_files)
            console.print(f"  Adapted {len(test_files)} test file(s)\n")
        else:
            console.print("  [yellow]Max iterations reached.[/]")

    # Step 5: Write outputs
    console.print(f"\n[bold cyan]Step 5:[/] Writing output to [bold]{project_dir}[/]")
    write_files(f"{project_dir}/src", code_files)
    write_files(f"{project_dir}/tests", test_files)
    console.print("  Done.\n")

    console.rule("[bold blue]Complete")

    return results
