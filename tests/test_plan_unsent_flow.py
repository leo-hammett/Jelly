from jelly.tui.screens.plan import (
    ACTION_EXECUTE,
    ACTION_PREVIEW,
    ACTION_SAVE_AND_BACK,
    UNSENT_CHOICE_CANCEL,
    UNSENT_CHOICE_CONTINUE_WITHOUT_SEND,
    UNSENT_CHOICE_SEND_AND_CONTINUE,
    normalize_unsent_choice,
    should_prompt_for_unsent_text,
)


def test_should_prompt_for_unsent_text_on_requested_actions() -> None:
    assert should_prompt_for_unsent_text("draft response", ACTION_SAVE_AND_BACK) is True
    assert should_prompt_for_unsent_text("draft response", ACTION_PREVIEW) is True
    assert should_prompt_for_unsent_text("draft response", ACTION_EXECUTE) is True


def test_should_not_prompt_with_empty_input() -> None:
    assert should_prompt_for_unsent_text("", ACTION_SAVE_AND_BACK) is False
    assert should_prompt_for_unsent_text("   ", ACTION_PREVIEW) is False


def test_normalize_unsent_choice_rejects_unknown_values() -> None:
    assert normalize_unsent_choice(UNSENT_CHOICE_SEND_AND_CONTINUE) == (
        UNSENT_CHOICE_SEND_AND_CONTINUE
    )
    assert normalize_unsent_choice(UNSENT_CHOICE_CONTINUE_WITHOUT_SEND) == (
        UNSENT_CHOICE_CONTINUE_WITHOUT_SEND
    )
    assert normalize_unsent_choice(UNSENT_CHOICE_CANCEL) == UNSENT_CHOICE_CANCEL
    assert normalize_unsent_choice("unexpected") == UNSENT_CHOICE_CANCEL
    assert normalize_unsent_choice(None) == UNSENT_CHOICE_CANCEL
