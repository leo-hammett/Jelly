import pytest

from jelly.tui.splitter import PaneSplitter


def test_splitter_requires_known_orientation() -> None:
    with pytest.raises(ValueError, match="orientation"):
        PaneSplitter("diagonal", "#left", "#right")


def test_clamp_before_size_respects_min_bounds() -> None:
    splitter = PaneSplitter("vertical", "#left", "#right", min_before=24, min_after=16)
    splitter._drag_available = 60

    assert splitter._clamp_before_size(10) == 24
    assert splitter._clamp_before_size(100) == 44


def test_clamp_before_size_handles_tight_space() -> None:
    splitter = PaneSplitter("horizontal", "#top", "#bottom", min_before=10, min_after=10)
    splitter._drag_available = 12

    assert splitter._clamp_before_size(1) == 1
    assert splitter._clamp_before_size(9) == 2
