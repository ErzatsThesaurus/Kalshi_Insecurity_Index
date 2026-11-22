"""The alert record shape that the ntfy and Healthchecks wiring reads.

Kept in one place because consistency across sleeves is the whole point: an
operator seeing `series_not_discovered` should not have to know which script
emitted it.

Levels:
    critical  index-affecting. Under --strict this exits 2, fails the systemd
              unit, and suppresses the Healthchecks ping so the dead-man's
              switch fires too.
    warning   worth seeing, does not fail the run.
"""

from __future__ import annotations

CRITICAL = "critical"
WARNING = "warning"


class AlertLog:
    """An ordered list of alert records raised during one snapshot."""

    def __init__(self) -> None:
        self._items: list[dict] = []

    def add(self, level: str, kind: str, detail: str, **context) -> dict:
        record = {"level": level, "kind": kind, "detail": detail, **context}
        self._items.append(record)
        return record

    def critical(self, kind: str, detail: str, **context) -> dict:
        return self.add(CRITICAL, kind, detail, **context)

    def warning(self, kind: str, detail: str, **context) -> dict:
        return self.add(WARNING, kind, detail, **context)

    @property
    def items(self) -> list[dict]:
        return list(self._items)

    @property
    def criticals(self) -> list[dict]:
        return [a for a in self._items if a["level"] == CRITICAL]

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)
