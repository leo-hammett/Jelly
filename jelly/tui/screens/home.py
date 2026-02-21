from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, ListItem, ListView, ProgressBar, Static


class HomeScreen(Screen):
    """Dashboard: pick a requirements file, see its readiness score, launch actions."""

    BINDINGS = [
        ("p", "plan", "Plan Mode"),
        ("e", "execute", "Execute"),
        ("r", "view_requirements", "View Requirements"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._md_files: list[Path] = []
        self._selected_path: Path | None = None
        self._score_data: dict | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="home-container"):
            yield Static("[b]JELLY[/b] -- Multi-Agent Coding System", id="home-title")
            with Horizontal(id="home-body"):
                with Vertical(id="file-panel"):
                    yield Static("Requirements Files", id="file-panel-title")
                    yield ListView(id="file-list")
                with Vertical(id="score-panel"):
                    yield Static("Readiness Score", id="score-title")
                    yield Static("--", id="score-value")
                    yield ProgressBar(total=100, show_eta=False, id="score-bar")
                    yield Static("", id="score-details")
                    yield Static("", id="suggestions-box")
            with Horizontal(classes="action-bar"):
                yield Button("Plan [P]", id="btn-plan", variant="primary")
                yield Button("Execute [E]", id="btn-execute", variant="success")
                yield Button("View [R]", id="btn-view", variant="default")
                yield Button("Quit [Q]", id="btn-quit", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self._scan_files()

    def _scan_files(self) -> None:
        cwd = Path.cwd()
        self._md_files = sorted(
            (p for p in cwd.glob("*.md")
             if p.name.lower() not in {"readme.md", "changelog.md", "license.md"}),
            key=lambda p: (0 if "requirement" in p.name.lower() else 1, p.name),
        )

        list_view = self.query_one("#file-list", ListView)
        list_view.clear()

        if not self._md_files:
            list_view.append(ListItem(Label("[dim]No .md files found[/dim]")))
            return

        for path in self._md_files:
            list_view.append(ListItem(Label(path.name), name=str(path)))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if not self._md_files:
            return
        idx = event.list_view.index
        if idx is not None and idx < len(self._md_files):
            self._selected_path = self._md_files[idx]
            self._score_selected()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if not self._md_files:
            return
        idx = event.list_view.index
        if idx is not None and idx < len(self._md_files):
            self._selected_path = self._md_files[idx]
            self._score_selected()

    @work(thread=True, exclusive=True, group="score")
    def _score_selected(self) -> None:
        if self._selected_path is None:
            return

        self.app.call_from_thread(
            self.query_one("#score-value", Static).update,
            "[dim]Scoring...[/dim]",
        )

        from jelly.agents.judge import Judge
        from jelly.config import Config

        judge = Judge(Config())
        text = self._selected_path.read_text()
        result = judge.score(text)
        self._score_data = result

        score = result["score"]
        if score >= 70:
            color = "green"
        elif score >= 40:
            color = "yellow"
        else:
            color = "red"

        self.app.call_from_thread(
            self.query_one("#score-value", Static).update,
            f"[bold {color}]{score}[/bold {color}] / 100",
        )
        bar = self.query_one("#score-bar", ProgressBar)
        self.app.call_from_thread(bar.update, progress=score)

        dims = result.get("dimensions", {})
        detail_lines = []
        for name, data in dims.items():
            label = name.replace("_", " ").title()
            s = data.get("score", 0)
            detail_lines.append(f"  {label}: {s}/20")
        self.app.call_from_thread(
            self.query_one("#score-details", Static).update,
            "\n".join(detail_lines),
        )

        suggestions = result.get("suggestions", [])
        if suggestions:
            sug_text = "[b]Suggestions:[/b]\n" + "\n".join(
                f"  - {s}" for s in suggestions[:3]
            )
        else:
            sug_text = ""
        self.app.call_from_thread(
            self.query_one("#suggestions-box", Static).update,
            sug_text,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn-plan":
            self.action_plan()
        elif button_id == "btn-execute":
            self.action_execute()
        elif button_id == "btn-view":
            self.action_view_requirements()
        elif button_id == "btn-quit":
            self.action_quit()

    def action_plan(self) -> None:
        from jelly.tui.screens.plan import PlanScreen

        existing = str(self._selected_path) if self._selected_path else None
        self.app.push_screen(PlanScreen(existing_requirements_path=existing))

    def action_execute(self) -> None:
        if self._selected_path is None:
            self.notify("Select a requirements file first", severity="warning")
            return
        from jelly.tui.screens.execute import ExecuteScreen

        self.app.push_screen(ExecuteScreen(str(self._selected_path)))

    def action_view_requirements(self) -> None:
        if self._selected_path is None:
            self.notify("Select a requirements file first", severity="warning")
            return
        from jelly.tui.screens.requirements import RequirementsScreen

        self.app.push_screen(RequirementsScreen(str(self._selected_path)))

    def action_quit(self) -> None:
        self.app.exit()
