from __future__ import annotations

import os
import subprocess
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Markdown, Static


class RequirementsScreen(Screen):
    """Read-only markdown viewer for a requirements file."""

    BINDINGS = [
        ("e", "edit", "Edit in $EDITOR"),
        ("escape", "go_back", "Back"),
    ]

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self._file_path = file_path

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="req-container"):
            yield Static(
                f"[b]Requirements:[/b] {Path(self._file_path).name}",
                id="req-title",
            )
            yield Markdown("", id="req-markdown")
            with Horizontal(id="req-footer"):
                yield Button("Edit [E]", id="btn-edit", variant="primary")
                yield Button("Back [Esc]", id="btn-back", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self._load_file()

    def _load_file(self) -> None:
        try:
            content = Path(self._file_path).read_text()
        except FileNotFoundError:
            content = f"*File not found: {self._file_path}*"
        self.query_one("#req-markdown", Markdown).update(content)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-edit":
            self.action_edit()
        elif event.button.id == "btn-back":
            self.action_go_back()

    def action_edit(self) -> None:
        editor = os.environ.get("EDITOR", "vi")
        with self.app.suspend():
            subprocess.call([editor, self._file_path])
        self._load_file()
        self.notify("File reloaded after editing")

    def action_go_back(self) -> None:
        self.app.pop_screen()
