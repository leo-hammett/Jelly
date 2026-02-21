from __future__ import annotations

from textual.app import App

from jelly.tui.screens.home import HomeScreen


class JellyApp(App):
    """Jelly TUI -- control panel for the multi-agent coding system."""

    TITLE = "Jelly"
    SUB_TITLE = "Multi-Agent Coding System"
    CSS_PATH = "jelly.tcss"

    SCREENS = {
        "home": HomeScreen,
    }

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())


def run_tui() -> None:
    """Launch the Jelly TUI application."""
    app = JellyApp()
    app.run()
