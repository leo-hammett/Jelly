from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from jelly.orchestrator import ProgressEvent, run_task

STEP_LABELS = {
    1: "Design tests",
    2: "Generate code",
    3: "Adapt tests",
    4: "Test & iterate",
    5: "Write output",
}

STATUS_ICONS = {
    "pending": "[dim]   [/dim]",
    "running": "[yellow] >> [/yellow]",
    "complete": "[green] OK [/green]",
    "failed": "[red]FAIL[/red]",
}


class StepWidget(Static):
    """Displays one pipeline step with icon, title, and detail."""

    def __init__(self, step_num: int) -> None:
        super().__init__()
        self.step_num = step_num
        self._status = "pending"
        self._detail = ""
        self._render_content()

    def set_status(self, status: str, detail: str = "") -> None:
        self._status = status
        self._detail = detail
        self._render_content()

    def _render_content(self) -> None:
        icon = STATUS_ICONS.get(self._status, STATUS_ICONS["pending"])
        label = STEP_LABELS.get(self.step_num, f"Step {self.step_num}")
        detail = f"  [dim]{self._detail}[/dim]" if self._detail else ""
        self.update(f" {icon}  Step {self.step_num}: {label}{detail}")


class ExecuteScreen(Screen):
    """Live pipeline progress display for the generate-test-fix loop."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
    ]

    def __init__(self, requirements_path: str, project_dir: str = "./output") -> None:
        super().__init__()
        self._req_path = requirements_path
        self._project_dir = project_dir
        self._steps: dict[int, StepWidget] = {}
        self._finished = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="exec-container"):
            yield Static("[b]EXECUTION[/b]", id="exec-title")
            with Vertical(id="steps-panel"):
                for i in range(1, 6):
                    sw = StepWidget(i)
                    self._steps[i] = sw
                    yield sw
            yield Static("[b]Log[/b]", id="exec-log-title")
            with VerticalScroll(id="exec-log"):
                yield Static(
                    f"[dim]Running pipeline on {self._req_path}...[/dim]",
                    classes="system-message",
                )
            with Horizontal(id="exec-footer"):
                yield Button("Back [Esc]", id="btn-back", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self._run_pipeline()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.action_go_back()

    @work(thread=True, exclusive=True, group="execute")
    def _run_pipeline(self) -> None:
        def on_progress(event: ProgressEvent) -> None:
            self.app.call_from_thread(self._handle_event, event)

        try:
            results = run_task(self._req_path, self._project_dir, on_progress)
            self._finished = True

            if results.get("all_passed"):
                summary = (
                    f"[bold green]All {results['total_tests']} tests passed![/bold green]"
                )
            else:
                summary = (
                    f"[bold red]{results['failed']}/{results['total_tests']} "
                    f"tests failed[/bold red]"
                )

            self.app.call_from_thread(self._log, summary)
            self.app.call_from_thread(
                self._log,
                f"[dim]Output written to {self._project_dir}/[/dim]",
            )

        except Exception as exc:
            self._finished = True
            self.app.call_from_thread(
                self._log,
                f"[bold red]Pipeline error: {exc}[/bold red]",
            )

    def _handle_event(self, event: ProgressEvent) -> None:
        step_widget = self._steps.get(event.step)
        if step_widget:
            step_widget.set_status(event.status, event.detail)

        if event.detail:
            self._log(f"Step {event.step}: {event.detail}")

    def _log(self, text: str) -> None:
        log = self.query_one("#exec-log", VerticalScroll)
        widget = Static(text, classes="system-message")
        log.mount(widget)
        widget.scroll_visible()

    def action_go_back(self) -> None:
        self.app.pop_screen()
