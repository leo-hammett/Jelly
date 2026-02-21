from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LEVEL_RANK = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


def _level_value(level: str) -> int:
    return _LEVEL_RANK.get(level.upper(), _LEVEL_RANK["INFO"])


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


@dataclass
class RunLogger:
    """Writes one JSON object per line for each pipeline event."""

    run_id: str
    log_file: Path
    level: str = "INFO"
    base_fields: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        log_dir: str | Path,
        level: str = "INFO",
        run_id: str | None = None,
        **base_fields: Any,
    ) -> "RunLogger":
        resolved_run_id = run_id or uuid.uuid4().hex[:12]
        log_root = Path(log_dir)
        log_root.mkdir(parents=True, exist_ok=True)
        log_file = log_root / f"run_{resolved_run_id}.jsonl"
        return cls(
            run_id=resolved_run_id,
            log_file=log_file,
            level=level.upper(),
            base_fields=base_fields,
        )

    def child(self, **base_fields: Any) -> "RunLogger":
        merged = dict(self.base_fields)
        merged.update(base_fields)
        return RunLogger(
            run_id=self.run_id,
            log_file=self.log_file,
            level=self.level,
            base_fields=merged,
        )

    def should_log(self, level: str) -> bool:
        return _level_value(level) >= _level_value(self.level)

    def event(
        self,
        level: str,
        component: str,
        operation: str,
        **fields: Any,
    ) -> None:
        if not self.should_log(level):
            return

        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level.upper(),
            "run_id": self.run_id,
            "component": component,
            "operation": operation,
        }
        payload.update(self.base_fields)
        payload.update(fields)
        safe_payload = _json_safe(payload)
        with self.log_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(safe_payload, ensure_ascii=False) + "\n")

    def timed(
        self,
        component: str,
        operation: str,
        level: str = "INFO",
        **fields: Any,
    ) -> "_TimedEvent":
        return _TimedEvent(self, component, operation, level.upper(), fields)


class _TimedEvent:
    def __init__(
        self,
        logger: RunLogger,
        component: str,
        operation: str,
        level: str,
        fields: dict[str, Any],
    ) -> None:
        self.logger = logger
        self.component = component
        self.operation = operation
        self.level = level
        self.fields = fields
        self._start = 0.0

    def __enter__(self) -> "_TimedEvent":
        self._start = time.perf_counter()
        self.logger.event(
            "DEBUG",
            self.component,
            f"{self.operation}.start",
            **self.fields,
        )
        return self

    def __exit__(self, exc_type, exc, _tb) -> bool:
        duration_ms = round((time.perf_counter() - self._start) * 1000.0, 2)
        if exc is None:
            self.logger.event(
                self.level,
                self.component,
                self.operation,
                duration_ms=duration_ms,
                **self.fields,
            )
            return False

        self.logger.event(
            "ERROR",
            self.component,
            self.operation,
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
            error_message=str(exc),
            **self.fields,
        )
        return False
