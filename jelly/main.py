import sys

import click
from rich.console import Console

from jelly.orchestrator import run_task

console = Console()


@click.group()
def cli() -> None:
    """Jelly: Multi-Agent Coding System."""


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


if __name__ == "__main__":
    cli()
