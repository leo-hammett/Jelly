from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Markdown, Static


def write_execution_draft(draft_text: str, source_path: str | None) -> Path:
    """Persist generated draft requirements to a temporary, executable file."""
    tmp_root = Path.cwd() / ".jelly_tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)

    stem = "requirements"
    if source_path:
        candidate = Path(source_path).stem.strip()
        if candidate:
            stem = candidate

    out_path = tmp_root / f"{stem}_draft_{uuid4().hex[:8]}.md"
    out_path.write_text(draft_text)
    return out_path


class PlanPreviewScreen(Screen):
    """Preview generated requirements draft before execution."""

    BINDINGS = [
        ("e", "execute", "Execute"),
        ("escape", "go_back", "Back"),
    ]

    def __init__(self, draft_text: str, source_path: str | None = None) -> None:
        super().__init__()
        self._draft_text = draft_text
        self._source_path = source_path

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="plan-preview-container"):
            yield Static("Generated Requirements Preview", id="plan-preview-title")
            yield Markdown("", id="plan-preview-markdown")
            with Horizontal(id="plan-preview-footer"):
                yield Button("Execute [E]", id="btn-execute", variant="success")
                yield Button("Back [Esc]", id="btn-back", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#plan-preview-markdown", Markdown).update(self._draft_text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-execute":
            self.action_execute()
        elif event.button.id == "btn-back":
            self.action_go_back()

    def action_execute(self) -> None:
        from jelly.tui.screens.execute import ExecuteScreen

        draft_path = write_execution_draft(self._draft_text, self._source_path)
        self.notify(f"Executing draft: {draft_path.name}")
        self.app.push_screen(ExecuteScreen(str(draft_path)))

    def action_go_back(self) -> None:
        self.app.pop_screen()
