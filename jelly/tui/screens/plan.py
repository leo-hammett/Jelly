from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Static

from jelly.agents.planner import Planner
from jelly.config import Config
from jelly.tui.splitter import PaneSplitter


class PlanScreen(Screen):
    """Interactive Q&A with the Planner agent and live Judge readiness score."""

    BINDINGS = [
        ("ctrl+d", "finalize", "Finalize & Save"),
        ("ctrl+r", "preview", "Preview Requirements"),
        ("ctrl+i", "suggest", "Suggest Implementation"),
        ("escape", "go_back", "Back"),
    ]

    def __init__(self, existing_requirements_path: str | None = None) -> None:
        super().__init__()
        self._req_path = existing_requirements_path
        self._config = Config()
        self._planner = Planner(self._config)
        self._exchange_count = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="plan-container"):
            with Horizontal(id="plan-header"):
                yield Static("[b]PLAN MODE[/b]", id="plan-header-title")
                yield Static("Score: [dim]--[/dim]", id="plan-score-label")
            with VerticalScroll(id="conversation-log"):
                yield Static(
                    "[dim italic]Starting planner...[/dim italic]",
                    classes="system-message",
                )
            yield PaneSplitter(
                orientation="horizontal",
                before="#conversation-log",
                after="#plan-input-area",
                id="plan-splitter",
                min_before=8,
                min_after=8,
            )
            with Vertical(id="plan-input-area"):
                yield Input(
                    placeholder="Type your response and press Enter...",
                    id="plan-input",
                )
                with Horizontal(classes="action-bar"):
                    yield Button("Send", id="btn-send", variant="primary")
                    yield Button("Finalize [^D]", id="btn-finalize", variant="success")
                    yield Button("Preview [^R]", id="btn-preview", variant="default")
                    yield Button("Suggest Impl [^I]", id="btn-suggest", variant="warning")
                    yield Button("Back [Esc]", id="btn-back", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self._start_conversation()

    @work(thread=True, exclusive=True, group="planner")
    def _start_conversation(self) -> None:
        existing_text = None
        if self._req_path:
            p = Path(self._req_path)
            if p.exists():
                existing_text = p.read_text()

        if existing_text:
            description = (
                "I have an existing requirements document that I'd like to "
                "refine. Here it is:\n\n" + existing_text
            )
            response = self._planner.start(description)
        else:
            response = self._planner.start()

        self.app.call_from_thread(self._append_message, "assistant", response)
        self.app.call_from_thread(
            self.query_one("#plan-input", Input).focus,
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self._append_message("user", text)
        self._send_to_planner(text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-send":
            inp = self.query_one("#plan-input", Input)
            text = inp.value.strip()
            if text:
                inp.value = ""
                self._append_message("user", text)
                self._send_to_planner(text)
        elif bid == "btn-finalize":
            self.action_finalize()
        elif bid == "btn-preview":
            self.action_preview()
        elif bid == "btn-suggest":
            self.action_suggest()
        elif bid == "btn-back":
            self.action_go_back()

    @work(thread=True, exclusive=True, group="planner")
    def _send_to_planner(self, user_text: str) -> None:
        self.app.call_from_thread(
            self._append_message, "system", "[dim]Thinking...[/dim]"
        )
        response = self._planner.respond(user_text)
        self.app.call_from_thread(self._remove_last_system)
        self.app.call_from_thread(self._append_message, "assistant", response)

        self._exchange_count += 1
        if self._exchange_count >= 2:
            self._update_score()

    @work(thread=True, exclusive=True, group="score")
    def _update_score(self) -> None:
        self.app.call_from_thread(
            self.query_one("#plan-score-label", Static).update,
            "Score: [dim]scoring...[/dim]",
        )

        try:
            draft = self._planner.generate_requirements()
        except Exception:
            return

        from jelly.agents.judge import Judge

        judge = Judge(self._config)
        result = judge.score(draft)
        score = result["score"]

        if score >= 70:
            color = "green"
        elif score >= 40:
            color = "yellow"
        else:
            color = "red"

        self.app.call_from_thread(
            self.query_one("#plan-score-label", Static).update,
            f"Score: [bold {color}]{score}/100[/bold {color}]",
        )

    def _append_message(self, role: str, content: str) -> None:
        log = self.query_one("#conversation-log", VerticalScroll)
        if role == "user":
            widget = Static(f"[b]You:[/b] {content}", classes="user-message")
        elif role == "assistant":
            widget = Static(f"[b]Planner:[/b] {content}", classes="assistant-message")
        else:
            widget = Static(content, classes="system-message")
        log.mount(widget)
        widget.scroll_visible()

    def _remove_last_system(self) -> None:
        log = self.query_one("#conversation-log", VerticalScroll)
        system_msgs = log.query(".system-message")
        if system_msgs:
            system_msgs.last().remove()

    def action_finalize(self) -> None:
        self._append_message("system", "[dim]Generating final requirements...[/dim]")
        self._do_finalize()

    @work(thread=True, exclusive=True, group="planner")
    def _do_finalize(self) -> None:
        requirements_md = self._planner.generate_requirements()

        if self._req_path:
            out_path = Path(self._req_path)
        else:
            base = "requirements.md"
            out_path = Path.cwd() / base
            counter = 1
            while out_path.exists():
                out_path = Path.cwd() / f"requirements_{counter}.md"
                counter += 1

        out_path.write_text(requirements_md)

        self.app.call_from_thread(self._remove_last_system)
        self.app.call_from_thread(
            self._append_message,
            "system",
            f"[green]Requirements saved to {out_path.name}[/green]",
        )
        self.app.call_from_thread(
            self.notify,
            f"Saved to {out_path}",
            title="Requirements Saved",
        )

    def action_preview(self) -> None:
        self._append_message("system", "[dim]Generating preview...[/dim]")
        self._do_preview()

    @work(thread=True, exclusive=True, group="planner")
    def _do_preview(self) -> None:
        draft = self._planner.generate_requirements()
        self.app.call_from_thread(self._remove_last_system)
        self.app.call_from_thread(
            self._append_message, "system",
            f"[dim]--- Requirements Preview ---[/dim]\n{draft}\n[dim]--- End Preview ---[/dim]",
        )

    def action_suggest(self) -> None:
        self._append_message("system", "[dim]Getting implementation suggestions...[/dim]")
        self._do_suggest()

    @work(thread=True, exclusive=True, group="planner")
    def _do_suggest(self) -> None:
        suggestion = self._planner.suggest_implementation()
        self.app.call_from_thread(self._remove_last_system)
        self.app.call_from_thread(self._append_message, "assistant", suggestion)

    def action_go_back(self) -> None:
        self.app.pop_screen()
