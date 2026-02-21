from __future__ import annotations

from textual import events
from textual.widget import Widget
from textual.widgets import Static


class PaneSplitter(Static):
    """A draggable splitter that resizes two panes."""

    def __init__(
        self,
        orientation: str,
        before: str,
        after: str,
        min_before: int = 20,
        min_after: int = 20,
        **kwargs,
    ) -> None:
        if orientation not in {"vertical", "horizontal"}:
            raise ValueError("orientation must be 'vertical' or 'horizontal'")

        extra_classes = kwargs.pop("classes", "")
        base_classes = f"pane-splitter pane-splitter-{orientation}"
        merged_classes = f"{base_classes} {extra_classes}".strip()
        super().__init__("", classes=merged_classes, **kwargs)

        self.orientation = orientation
        self.before_query = before
        self.after_query = after
        self.min_before = min_before
        self.min_after = min_after

        self._dragging = False
        self._drag_start_pointer = 0
        self._drag_start_before_size = 0
        self._drag_available = 0

    @property
    def _is_vertical(self) -> bool:
        return self.orientation == "vertical"

    def _pointer_coord(self, event: events.MouseEvent) -> int:
        return event.screen_x if self._is_vertical else event.screen_y

    def _pane_size(self, pane: Widget) -> int:
        return pane.size.width if self._is_vertical else pane.size.height

    def _resolve_panes(self) -> tuple[Widget, Widget] | None:
        try:
            before = self.screen.query_one(self.before_query, Widget)
            after = self.screen.query_one(self.after_query, Widget)
        except Exception:
            return None
        return before, after

    def _clamp_before_size(self, proposed_size: int) -> int:
        available = max(2, self._drag_available)
        min_before = max(1, min(self.min_before, available - 1))
        max_before = max(1, available - self.min_after)

        # If requested mins cannot both fit, keep at least one cell for each pane.
        if max_before < min_before:
            min_before = 1

        return max(min_before, min(proposed_size, max_before))

    def _apply_before_size(self, before: Widget, after: Widget, size: int) -> None:
        if self._is_vertical:
            before.styles.width = size
            after.styles.width = "1fr"
        else:
            before.styles.height = size
            after.styles.height = "1fr"
        self.refresh(layout=True)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1:
            return

        panes = self._resolve_panes()
        if panes is None:
            return

        before, after = panes
        before_size = self._pane_size(before)
        after_size = self._pane_size(after)
        if before_size <= 0 or after_size <= 0:
            return

        self._dragging = True
        self._drag_start_pointer = self._pointer_coord(event)
        self._drag_start_before_size = before_size
        self._drag_available = before_size + after_size

        self.capture_mouse(True)
        self.set_class(True, "dragging")
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return

        panes = self._resolve_panes()
        if panes is None:
            return

        before, after = panes
        delta = self._pointer_coord(event) - self._drag_start_pointer
        new_size = self._clamp_before_size(self._drag_start_before_size + delta)
        self._apply_before_size(before, after, new_size)
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._dragging or event.button != 1:
            return

        self._dragging = False
        self.capture_mouse(False)
        self.set_class(False, "dragging")
        event.stop()
