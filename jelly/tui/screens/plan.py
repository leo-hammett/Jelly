from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Static

from jelly.agents.planner import Planner
from jelly.config import Config
from jelly.tui.splitter import PaneSplitter
from jelly.tui.widgets import AnimatedLoading, ShimmerLabel

ACTION_SAVE_AND_BACK = "save_and_back"
ACTION_PREVIEW = "preview"
ACTION_EXECUTE = "execute"

UNSENT_CHOICE_SEND_AND_CONTINUE = "send_and_continue"
UNSENT_CHOICE_CONTINUE_WITHOUT_SEND = "continue_without_send"
UNSENT_CHOICE_CANCEL = "cancel"

ACTION_LABELS = {
    ACTION_SAVE_AND_BACK: "Save and Back",
    ACTION_PREVIEW: "Preview",
    ACTION_EXECUTE: "Execute",
}


def should_prompt_for_unsent_text(input_text: str, action: str) -> bool:
    if action not in {ACTION_SAVE_AND_BACK, ACTION_PREVIEW, ACTION_EXECUTE}:
        return False
    return bool(input_text.strip())


def normalize_unsent_choice(choice: str | None) -> str:
    if choice in {
        UNSENT_CHOICE_SEND_AND_CONTINUE,
        UNSENT_CHOICE_CONTINUE_WITHOUT_SEND,
        UNSENT_CHOICE_CANCEL,
    }:
        return choice
    return UNSENT_CHOICE_CANCEL


class UnsentInputChoiceModal(ModalScreen[str]):
    """Decision modal shown when action is pressed with unsent text."""

    BINDINGS = [("escape", "dismiss_cancel", "Cancel")]

    def __init__(self, action_label: str) -> None:
        super().__init__()
        self._action_label = action_label

    def compose(self) -> ComposeResult:
        with Vertical(id="unsent-modal"):
            yield Static("Unsent text detected", id="unsent-modal-title")
            yield Static(
                (
                    "You have text in the input box that has not been sent.\n"
                    f"What should happen before {self._action_label}?"
                ),
                id="unsent-modal-text",
            )
            with Horizontal(id="unsent-modal-actions"):
                yield Button(
                    "Send and continue",
                    id="btn-unsent-send",
                    variant="success",
                )
                yield Button(
                    "Continue without sending",
                    id="btn-unsent-continue",
                    variant="warning",
                )
                yield Button("Cancel", id="btn-unsent-cancel", variant="error")

    def action_dismiss_cancel(self) -> None:
        self.dismiss(UNSENT_CHOICE_CANCEL)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-unsent-send":
            self.dismiss(UNSENT_CHOICE_SEND_AND_CONTINUE)
        elif bid == "btn-unsent-continue":
            self.dismiss(UNSENT_CHOICE_CONTINUE_WITHOUT_SEND)
        else:
            self.dismiss(UNSENT_CHOICE_CANCEL)


class PlanScreen(Screen):
    """Interactive Q&A with the Planner agent and live Judge readiness score."""

    BINDINGS = [
        ("ctrl+s", "save_and_back", "Save and Back"),
        ("ctrl+e", "execute", "Execute"),
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
        self._active_loading: AnimatedLoading | None = None
        self._pending_action: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="plan-container"):
            with Horizontal(id="plan-header"):
                yield ShimmerLabel("PLAN MODE", id="plan-header-title", fps=8.0)
                yield AnimatedLoading(
                    "Score: [dim]--[/dim]",
                    id="plan-score-label",
                    auto_start=False,
                    fps=8.0,
                    shimmer=False,
                    show_spinner=True,
                )
            with VerticalScroll(id="conversation-log"):
                yield AnimatedLoading(
                    "Starting planner...",
                    classes="system-message",
                    id="planner-startup-loading",
                    fps=10.0,
                )
            yield PaneSplitter(
                orientation="horizontal",
                before="#conversation-log",
                after="#plan-input-area",
                id="plan-splitter",
                min_before=8,
                min_after=7,
            )
            with Vertical(id="plan-input-area"):
                with Horizontal(id="plan-suggest-row"):
                    yield Button(
                        "Suggest Implementation [^I]",
                        id="btn-suggest",
                        variant="warning",
                    )
                with Horizontal(id="plan-input-row"):
                    yield Input(
                        placeholder="Type your response and press Enter...",
                        id="plan-input",
                    )
                    yield Button("↑", id="btn-send", variant="primary")
                with Horizontal(id="plan-action-row"):
                    yield Button(
                        "Save and Back [^S]",
                        id="btn-save-back",
                        variant="success",
                    )
                    yield Button("Execute [^E]", id="btn-execute", variant="primary")
                    yield Button("Preview [^R]", id="btn-preview", variant="default")
        yield Footer()

    def on_mount(self) -> None:
        self._active_loading = self.query_one("#planner-startup-loading", AnimatedLoading)
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

        self.app.call_from_thread(self._clear_loading)
        self.app.call_from_thread(self._append_message, "assistant", response)
        self.app.call_from_thread(
            self.query_one("#plan-input", Input).focus,
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        _ = event
        self._send_current_input()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-send":
            self._send_current_input()
        elif bid == "btn-save-back":
            self.action_save_and_back()
        elif bid == "btn-execute":
            self.action_execute()
        elif bid == "btn-preview":
            self.action_preview()
        elif bid == "btn-suggest":
            self.action_suggest()

    def _send_current_input(self) -> bool:
        inp = self.query_one("#plan-input", Input)
        text = inp.value.strip()
        if not text:
            return False
        inp.value = ""
        self._append_message("user", text)
        self._send_to_planner(text)
        return True

    @work(thread=True, exclusive=True, group="planner")
    def _send_to_planner(self, user_text: str) -> None:
        self.app.call_from_thread(
            self._show_loading,
            "Thinking...",
        )
        response = self._planner.respond(user_text)
        self.app.call_from_thread(self._clear_loading)
        self.app.call_from_thread(self._append_message, "assistant", response)

        self._exchange_count += 1
        if self._exchange_count >= 2:
            self._update_score()
        self.app.call_from_thread(self._continue_pending_action)

    @work(thread=True, exclusive=True, group="score")
    def _update_score(self) -> None:
        score_label = self.query_one("#plan-score-label", AnimatedLoading)
        self.app.call_from_thread(
            score_label.start,
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
            score_label.stop,
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

    def _show_loading(self, message: str) -> None:
        log = self.query_one("#conversation-log", VerticalScroll)
        self._clear_loading()
        widget = AnimatedLoading(message, classes="system-message", fps=10.0)
        self._active_loading = widget
        log.mount(widget)
        widget.scroll_visible()

    def _clear_loading(self) -> None:
        if self._active_loading is not None:
            try:
                self._active_loading.remove()
            except Exception:
                pass
            self._active_loading = None

    def action_save_and_back(self) -> None:
        self._request_action(ACTION_SAVE_AND_BACK)

    def action_execute(self) -> None:
        self._request_action(ACTION_EXECUTE)

    def action_preview(self) -> None:
        self._request_action(ACTION_PREVIEW)

    def _request_action(self, action: str) -> None:
        inp = self.query_one("#plan-input", Input)
        unsent_text = inp.value.strip()
        if should_prompt_for_unsent_text(unsent_text, action):
            self.app.push_screen(
                UnsentInputChoiceModal(ACTION_LABELS[action]),
                lambda choice: self._handle_unsent_choice(
                    action,
                    unsent_text,
                    normalize_unsent_choice(choice),
                ),
            )
            return
        self._perform_action(action)

    def _handle_unsent_choice(self, action: str, unsent_text: str, choice: str) -> None:
        if choice == UNSENT_CHOICE_CANCEL:
            return
        if choice == UNSENT_CHOICE_CONTINUE_WITHOUT_SEND:
            self._perform_action(action)
            return

        if not unsent_text.strip():
            self._perform_action(action)
            return

        inp = self.query_one("#plan-input", Input)
        if inp.value.strip() == unsent_text:
            inp.value = ""
        self._append_message("user", unsent_text)
        self._pending_action = action
        self._send_to_planner(unsent_text)

    def _continue_pending_action(self) -> None:
        if self._pending_action is None:
            return
        action = self._pending_action
        self._pending_action = None
        self._perform_action(action)

    def _perform_action(self, action: str) -> None:
        if action == ACTION_SAVE_AND_BACK:
            self._show_loading("Saving requirements...")
            self._do_save_and_back()
        elif action == ACTION_EXECUTE:
            self._show_loading("Preparing execution draft...")
            self._do_execute_from_draft()
        elif action == ACTION_PREVIEW:
            self._show_loading("Generating preview...")
            self._do_open_preview()

    @work(thread=True, exclusive=True, group="planner")
    def _do_save_and_back(self) -> None:
        requirements_md = self._planner.generate_requirements()
        out_path = self._resolve_requirements_path()
        out_path.write_text(requirements_md)
        self._req_path = str(out_path)
        self.app.call_from_thread(self._clear_loading)
        self.app.call_from_thread(
            self.notify,
            f"Saved to {out_path}",
            title="Requirements Saved",
        )
        self.app.call_from_thread(self.app.pop_screen)

    def action_suggest(self) -> None:
        self._show_loading("Getting implementation suggestions...")
        self._do_suggest()

    @work(thread=True, exclusive=True, group="planner")
    def _do_suggest(self) -> None:
        suggestion = self._planner.suggest_implementation()
        self.app.call_from_thread(self._clear_loading)
        self.app.call_from_thread(self._append_message, "assistant", suggestion)

    @work(thread=True, exclusive=True, group="planner")
    def _do_open_preview(self) -> None:
        draft = self._planner.generate_requirements()
        self.app.call_from_thread(self._clear_loading)
        self.app.call_from_thread(self._push_preview_screen, draft)

    def _push_preview_screen(self, draft: str) -> None:
        from jelly.tui.screens.plan_preview import PlanPreviewScreen

        self.app.push_screen(PlanPreviewScreen(draft_text=draft, source_path=self._req_path))

    @work(thread=True, exclusive=True, group="planner")
    def _do_execute_from_draft(self) -> None:
        draft = self._planner.generate_requirements()
        from jelly.tui.screens.plan_preview import write_execution_draft

        draft_path = write_execution_draft(draft, self._req_path)
        self.app.call_from_thread(self._clear_loading)
        self.app.call_from_thread(self._push_execute_screen, str(draft_path))

    def _push_execute_screen(self, draft_path: str) -> None:
        from jelly.tui.screens.execute import ExecuteScreen

        self._append_message(
            "system",
            f"[dim]Executing generated draft: {Path(draft_path).name}[/dim]",
        )
        self.app.push_screen(ExecuteScreen(draft_path))

    def _resolve_requirements_path(self) -> Path:
        if self._req_path:
            return Path(self._req_path)

        base = "requirements.md"
        out_path = Path.cwd() / base
        counter = 1
        while out_path.exists():
            out_path = Path.cwd() / f"requirements_{counter}.md"
            counter += 1
        return out_path

    def action_go_back(self) -> None:
        self.app.pop_screen()
