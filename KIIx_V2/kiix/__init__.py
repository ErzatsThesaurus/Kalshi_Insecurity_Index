"""Shared ingestion machinery for the KIIX political sleeves.

Layout:
    registry.py     the seven series, their sleeve, role and information horizon
    kalshi.py       HTTP client and series discovery
    convert.py      wire-format converters (decimal-dollar strings -> cents)
    schema.py       market normalization and ladder structure classification
    diagnostics.py  per-event quote and geometry diagnostics
    alerts.py       the alert record shape that ntfy/Healthchecks wiring reads
    snapshot.py     snapshot assembly, paths and idempotent writes
    cli.py          the flags and exit semantics shared by every sleeve script

Sleeve scripts stay thin: pick a sleeve, print a summary.
"""

__all__ = [
    "alerts",
    "cli",
    "convert",
    "diagnostics",
    "kalshi",
    "registry",
    "schema",
    "snapshot",
]
