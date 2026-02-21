import sys

import click
from rich.console import Console

from jelly.orchestrator import run_task

console = Console()


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Jelly: Multi-Agent Coding System."""
    if ctx.invoked_subcommand is None:
        from jelly.tui.app import run_tui

        run_tui()


@cli.command()
@click.argument("requirements_path", type=click.Path(exists=True))
@click.option(
    "--project-dir",
    default="./output",
    type=click.Path(),
    help="Output directory for generated code and tests.",
)
def run(requirements_path: str, project_dir: str) -> None:
    """Generate code from a requirements document, test it, and iterate.

    REQUIREMENTS_PATH is the path to a markdown requirements file.
    """
    try:
        results = run_task(requirements_path, project_dir)
        if not results.get("all_passed"):
            sys.exit(1)
    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Error:[/] {e}")
        sys.exit(1)


@cli.command()
def tui() -> None:
    """Launch the interactive TUI control panel."""
    from jelly.tui.app import run_tui

    run_tui()


@cli.command()
@click.argument("requirements_path", type=click.Path(exists=True))
def score(requirements_path: str) -> None:
    """Score a requirements document for readiness (0-100)."""
    from jelly.agents.judge import Judge
    from jelly.config import Config
    from jelly.utils import read_file

    try:
        text = read_file(requirements_path)
        judge = Judge(Config())
        result = judge.score(text)

        total = result["score"]
        ready = result["ready"]

        if total >= 70:
            color = "green"
        elif total >= 40:
            color = "yellow"
        else:
            color = "red"

        console.print(f"\n[bold]Readiness Score:[/] [bold {color}]{total}/100[/]")
        console.print(f"[bold]Ready:[/] {'Yes' if ready else 'No'}\n")

        for name, data in result.get("dimensions", {}).items():
            label = name.replace("_", " ").title()
            s = data.get("score", 0)
            feedback = data.get("feedback", "")
            console.print(f"  {label}: {s}/20  {feedback}")

        suggestions = result.get("suggestions", [])
        if suggestions:
            console.print("\n[bold]Suggestions:[/]")
            for s in suggestions:
                console.print(f"  - {s}")
        console.print()

    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Error:[/] {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()
