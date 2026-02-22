from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Button, Footer, Header, Static

from jelly.config import Config
from jelly.orchestrator import ProgressEvent, run_task
from jelly.tui.splitter import PaneSplitter
from jelly.tui.widgets import AnimatedLoading, ShimmerLabel

STEP_LABELS = {
    0: "Capability gate",
    1: "Design tests",
    2: "Generate code",
    3: "Adapt tests",
    4: "Test & iterate",
    5: "Write output",
}

STATUS_ICONS = {
    "pending": "[dim]   [/dim]",
    "running": "[yellow] >  [/yellow]",
    "complete": "[green] OK [/green]",
    "failed": "[red]FAIL[/red]",
}

RUNNING_ICONS = [
    "[#ff72c8] >  [/#ff72c8]",
    "[#ff72c8] >> [/#ff72c8]",
    "[#ff72c8]  > [/#ff72c8]",
    "[#ffd1f0] >> [/#ffd1f0]",
]


class StepWidget(Static):
    """Displays one pipeline step with icon, title, and detail."""

    def __init__(self, step_num: int) -> None:
        super().__init__()
        self.step_num = step_num
        self._status = "pending"
        self._detail = ""
        self._running_frame = 0
        self._running_timer: Timer | None = None
        self._render_content()

    def on_unmount(self) -> None:
        self._stop_running_animation()

    def set_status(self, status: str, detail: str = "") -> None:
        self._status = status
        self._detail = detail
        if status == "running":
            self._start_running_animation()
        else:
            self._stop_running_animation()
        self._render_content()

    def _start_running_animation(self) -> None:
        if self._running_timer is None:
            self._running_timer = self.set_interval(0.12, self._tick_running)

    def _stop_running_animation(self) -> None:
        if self._running_timer is not None:
            self._running_timer.stop()
            self._running_timer = None
        self._running_frame = 0

    def _tick_running(self) -> None:
        if self._status != "running":
            return
        self._running_frame = (self._running_frame + 1) % len(RUNNING_ICONS)
        self._render_content()

    def _render_content(self) -> None:
        if self._status == "running":
            icon = RUNNING_ICONS[self._running_frame]
        else:
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
        self._show_step0 = Config().enable_step2_pregnancy
        self._steps: dict[int, StepWidget] = {}
        self._finished = False
        self._startup_loading: AnimatedLoading | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="exec-container"):
            yield ShimmerLabel("EXECUTION", id="exec-title", fps=8.0)
            with Vertical(id="exec-main"):
                with Vertical(id="steps-panel"):
                    start_step = 0 if self._show_step0 else 1
                    for i in range(start_step, 6):
                        sw = StepWidget(i)
                        self._steps[i] = sw
                        yield sw
                yield PaneSplitter(
                    orientation="horizontal",
                    before="#steps-panel",
                    after="#exec-log-panel",
                    id="exec-splitter",
                    min_before=6,
                    min_after=8,
                )
                with Vertical(id="exec-log-panel"):
                    yield Static("[b]Log[/b]", id="exec-log-title")
                    with VerticalScroll(id="exec-log"):
                        yield AnimatedLoading(
                            f"Running pipeline on {self._req_path}...",
                            classes="system-message",
                            id="exec-startup-loading",
                            fps=10.0,
                        )
            with Horizontal(id="exec-footer"):
                yield Button("Back [Esc]", id="btn-back", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self._startup_loading = self.query_one("#exec-startup-loading", AnimatedLoading)
        self._run_pipeline()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.action_go_back()

    @work(thread=True, exclusive=True, group="execute")
    def _run_pipeline(self) -> None:
        def on_progress(event: ProgressEvent) -> None:
            self.app.call_from_thread(self._handle_event, event)

        try:
            self.app.call_from_thread(
                self._log,
                f"[#ffd1f0]Using requirements file:[/#ffd1f0] {self._req_path}",
            )
            for line in self._requirements_preview(max_lines=6):
                self.app.call_from_thread(self._log, line)
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
            mcp_summary = results.get("mcp_summary")
            if isinstance(mcp_summary, dict) and mcp_summary.get("steps_total", 0):
                self.app.call_from_thread(
                    self._log,
                    (
                        "[#ff72c8]MCP summary:[/#ff72c8] "
                        f"{mcp_summary.get('steps_passed', 0)}/"
                        f"{mcp_summary.get('steps_total', 0)} steps passed, "
                        f"{mcp_summary.get('servers_started', 0)}/"
                        f"{mcp_summary.get('servers_requested', 0)} servers started"
                    ),
                )
            self.app.call_from_thread(
                self._log,
                f"[dim]Output written to {self._project_dir}/[/dim]",
            )

        except Exception as exc:
            self._finished = True
            self.app.call_from_thread(self._clear_startup_loading)
            self.app.call_from_thread(
                self._log,
                f"[bold red]Pipeline error: {exc}[/bold red]",
            )

    def _handle_event(self, event: ProgressEvent) -> None:
        self._clear_startup_loading()
        step_widget = self._steps.get(event.step)
        if step_widget:
            step_widget.set_status(event.status, event.detail)

        self._log(self._format_event(event))

    def _format_event(self, event: ProgressEvent) -> str:
        status_labels = {
            "running": ("RUN", "yellow"),
            "complete": ("DONE", "green"),
            "failed": ("FAIL", "red"),
            "pending": ("WAIT", "white"),
        }
        status_text, color = status_labels.get(event.status, ("INFO", "white"))
        kind = ""
        if isinstance(event.meta, dict):
            kind = str(event.meta.get("kind", ""))
        kind_prefix = ""
        if kind.startswith("mcp"):
            kind_prefix = "[#ff72c8]MCP[/#ff72c8] "
        elif kind.startswith("capability"):
            kind_prefix = "[#ffd1f0]CAP[/#ffd1f0] "
        iteration = f" (iteration {event.iteration})" if event.iteration else ""
        detail = f" -- {event.detail}" if event.detail else ""
        return (
            f"[bold {color}][{status_text}][/bold {color}] "
            f"{kind_prefix}Step {event.step}: {event.title}{iteration}{detail}"
        )

    def _clear_startup_loading(self) -> None:
        if self._startup_loading is None:
            return
        try:
            self._startup_loading.remove()
        except Exception:
            pass
        self._startup_loading = None

    def _requirements_preview(self, max_lines: int = 6) -> list[str]:
        try:
            lines = Path(self._req_path).read_text().splitlines()
        except Exception as exc:
            return [f"[red]Could not preview requirements file: {exc}[/red]"]

        if not lines:
            return ["[dim]Requirements preview: file is empty.[/dim]"]

        preview = ["[dim]Requirements preview:[/dim]"]
        for idx, line in enumerate(lines[:max_lines], start=1):
            snippet = line.strip()
            if len(snippet) > 120:
                snippet = f"{snippet[:117]}..."
            preview.append(f"[dim]  {idx:02d} | {snippet}[/dim]")

        remaining = len(lines) - max_lines
        if remaining > 0:
            preview.append(f"[dim]  ... ({remaining} more line(s))[/dim]")
        return preview

    def _log(self, text: str) -> None:
        log = self.query_one("#exec-log", VerticalScroll)
        widget = Static(text, classes="system-message")
        log.mount(widget)
        widget.scroll_visible()

    def action_go_back(self) -> None:
        self.app.pop_screen()
