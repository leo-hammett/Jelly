from __future__ import annotations

from textual.timer import Timer
from textual.widgets import Static

SPINNER_FRAMES = ["[=   ]", "[==  ]", "[=== ]", "[ ===]", "[  ==]", "[   =]"]
SHIMMER_PALETTE = [
    "#a3478c",
    "#c95aa8",
    "#ff72c8",
    "#ff9fda",
    "#ffd1f0",
    "#fff6ff",
    "#ffd1f0",
    "#ff9fda",
    "#ff72c8",
    "#c95aa8",
]


def _shimmer_markup(text: str, offset: int) -> str:
    if not text:
        return text
    rendered: list[str] = []
    palette_size = len(SHIMMER_PALETTE)
    for index, char in enumerate(text):
        if char == " ":
            rendered.append(char)
            continue
        color = SHIMMER_PALETTE[(index + offset) % palette_size]
        rendered.append(f"[{color}]{char}[/{color}]")
    return "".join(rendered)


class AnimatedLoading(Static):
    """Frame-based loading text with jelly-pink shimmer."""

    def __init__(
        self,
        message: str,
        *,
        fps: float = 12.0,
        shimmer: bool = True,
        show_spinner: bool = True,
        auto_start: bool = True,
        **kwargs,
    ) -> None:
        super().__init__("", **kwargs)
        self._message = message
        self._fps = max(1.0, fps)
        self._shimmer = shimmer
        self._show_spinner = show_spinner
        self._active = auto_start
        self._frame_index = 0
        self._wave_offset = 0
        self._timer: Timer | None = None

    @property
    def is_active(self) -> bool:
        return self._active

    def on_mount(self) -> None:
        self._render_display()
        if self._active:
            self._start_timer()

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def start(self, message: str | None = None) -> None:
        if message is not None:
            self._message = message
        self._active = True
        self._render_display()
        self._start_timer()

    def stop(self, final_text: str | None = None) -> None:
        self._active = False
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if final_text is not None:
            self.update(final_text)
        else:
            self.update(self._message)

    def set_message(self, message: str) -> None:
        self._message = message
        self._render_display()

    def _start_timer(self) -> None:
        if self._timer is None:
            self._timer = self.set_interval(1.0 / self._fps, self._advance_frame)

    def _advance_frame(self) -> None:
        if not self._active:
            return
        self._frame_index = (self._frame_index + 1) % len(SPINNER_FRAMES)
        self._wave_offset = (self._wave_offset + 1) % len(SHIMMER_PALETTE)
        self._render_display()

    def _render_display(self) -> None:
        if not self._active:
            self.update(self._message)
            return

        message_text = (
            _shimmer_markup(self._message, self._wave_offset)
            if self._shimmer
            else self._message
        )
        if self._show_spinner:
            frame = SPINNER_FRAMES[self._frame_index]
            self.update(f"[bold #ff72c8]{frame}[/bold #ff72c8] {message_text}")
            return
        self.update(message_text)


class ShimmerLabel(Static):
    """A continuously shimmering label for titles and accents."""

    def __init__(
        self,
        text: str,
        *,
        fps: float = 10.0,
        **kwargs,
    ) -> None:
        super().__init__("", **kwargs)
        self._text = text
        self._fps = max(1.0, fps)
        self._offset = 0
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        self._render_display()
        self._timer = self.set_interval(1.0 / self._fps, self._tick)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        self._offset = (self._offset + 1) % len(SHIMMER_PALETTE)
        self._render_display()

    def _render_display(self) -> None:
        self.update(_shimmer_markup(self._text, self._offset))
