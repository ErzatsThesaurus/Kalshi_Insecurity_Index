"""Wire-format converters for Kalshi payloads.

Kalshi sends prices as decimal-dollar strings ("0.2900") and sizes, volumes and
open interest as string floats ("26731.16"). Both need converting once, at the
ingestion boundary, so nothing downstream parses strings.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def cents(value: object) -> int | None:
    """Decimal-dollar string or number -> integer cents.

    Decimal, not float, is load-bearing here. `int(0.29 * 100)` is 28, because
    0.29 has no exact binary representation and int() truncates toward zero. A
    silent one-cent error on arbitrary buckets would feed straight into the
    ladder-sum gate.
    """
    if value is None or value == "":
        return None
    try:
        return int((Decimal(str(value)) * 100).to_integral_value())
    except (InvalidOperation, ValueError):
        return None


def as_float(value: object) -> float | None:
    """String float or number -> float, with None for absent fields."""
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
