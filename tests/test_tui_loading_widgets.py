from jelly.tui.widgets import (
    SHIMMER_PALETTE,
    SPINNER_FRAMES,
    AnimatedLoading,
    ShimmerLabel,
    _shimmer_markup,
)


class _FakeTimer:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def test_shimmer_markup_preserves_spaces() -> None:
    rendered = _shimmer_markup("A B", offset=2)
    assert " " in rendered
    assert "A" in rendered
    assert "B" in rendered


def test_animated_loading_frame_progression_wraps() -> None:
    widget = AnimatedLoading("Loading", auto_start=False)
    widget._active = True
    widget._frame_index = len(SPINNER_FRAMES) - 1
    widget._wave_offset = len(SHIMMER_PALETTE) - 1

    widget._advance_frame()

    assert widget._frame_index == 0
    assert widget._wave_offset == 0


def test_animated_loading_stop_cleans_timer() -> None:
    widget = AnimatedLoading("Loading", auto_start=False)
    fake_timer = _FakeTimer()
    widget._timer = fake_timer
    widget._active = True

    widget.stop("Done")

    assert fake_timer.stopped is True
    assert widget._timer is None
    assert widget.is_active is False


def test_animated_loading_start_sets_message_without_mount(monkeypatch) -> None:
    widget = AnimatedLoading("Loading", auto_start=False)
    start_called = {"value": False}

    def _fake_start_timer() -> None:
        start_called["value"] = True

    monkeypatch.setattr(widget, "_start_timer", _fake_start_timer)
    widget.start("Scoring requirements...")

    assert start_called["value"] is True
    assert widget.is_active is True
    assert widget._message == "Scoring requirements..."


def test_shimmer_label_unmount_stops_timer() -> None:
    label = ShimmerLabel("JELLY")
    fake_timer = _FakeTimer()
    label._timer = fake_timer

    label.on_unmount()

    assert fake_timer.stopped is True
    assert label._timer is None


def test_shimmer_palette_stays_bright_on_dark_backgrounds() -> None:
    for color in SHIMMER_PALETTE:
        assert color.startswith("#")
        red = int(color[1:3], 16)
        green = int(color[3:5], 16)
        blue = int(color[5:7], 16)
        # Keep shimmer phases away from near-black so text stays readable.
        assert max(red, green, blue) >= 160
