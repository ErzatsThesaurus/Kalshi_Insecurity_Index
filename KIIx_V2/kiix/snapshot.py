"""Snapshot assembly, paths and idempotent writes.

One snapshot file per run, immutable. `captured_at` is fixed once per run and is
the snapshot's identity, which is what makes replay safe: re-running the same
`captured_at` writes nothing.

Files are sharded by UTC date because a 15-minute cadence puts ~96 files a day in
one directory:

    data/<sleeve>/2026/09/26/snapshot_20260926T054500Z.json
    data/<sleeve>/latest.json
    data/<sleeve>/.retired          (written past the information horizon)
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

from . import registry
from .alerts import AlertLog
from .diagnostics import event_diagnostics
from .kalshi import Client, discover_series, open_markets, orderbook, series_detail
from .schema import SCHEMA_VERSION, classify_ladder, normalize_market

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
# The board does not agree with itself about categories: approval is under
# Politics, the seat and chamber-control series only under Elections. Discovery
# unions both, so a recategorization by the exchange does not break ingestion.
CATEGORIES: tuple[str, ...] = ("Politics", "Elections")


# --------------------------------------------------------------------------- #
# paths and identity
# --------------------------------------------------------------------------- #

def make_captured_at(override: str | None = None) -> str:
    """The run's single timestamp. Second precision; UTC always."""
    if override:
        return override
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp(captured_at: str) -> str:
    return captured_at.replace(":", "").replace("-", "")


def sleeve_dir(sleeve: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / sleeve


def snapshot_path(
    sleeve: str, captured_at: str, data_dir: Path = DATA_DIR, shard: bool = True
) -> Path:
    """Where this run's snapshot belongs. shard=False gives the old flat layout."""
    base = sleeve_dir(sleeve, data_dir)
    name = f"snapshot_{_stamp(captured_at)}.json"
    if not shard:
        return base / name
    day = captured_at[:10].split("-")  # YYYY, MM, DD
    return base / day[0] / day[1] / day[2] / name


def write_snapshot(path: Path, snapshot: dict, sleeve: str, data_dir: Path = DATA_DIR) -> None:
    """Write the snapshot, then refresh the sleeve's latest.json pointer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    shutil.copyfile(path, sleeve_dir(sleeve, data_dir) / "latest.json")


# --------------------------------------------------------------------------- #
# retirement
# --------------------------------------------------------------------------- #

def retirement_marker(sleeve: str, data_dir: Path = DATA_DIR) -> Path:
    return sleeve_dir(sleeve, data_dir) / ".retired"


def is_retired(sleeve: str, today: date | None = None) -> tuple[bool, str | None]:
    """Whether the sleeve is past its information horizon.

    The spec retires a sleeve at its horizon rather than letting T go negative.
    systemd cannot express an end date on OnCalendar, so the marker file this
    drives is what the unit's ConditionPathExists tests.
    """
    horizon = registry.horizon_for_sleeve(sleeve)
    if horizon is None:
        return False, None  # constant-maturity; never retires
    today = today or datetime.now(timezone.utc).date()
    # Retired the day *after* the horizon: uncertainty collapses on election
    # night, so the horizon date itself is still a live trading day.
    return today > date.fromisoformat(horizon), horizon


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #

def _event_rows(markets: list[dict]) -> dict[str, list[dict]]:
    events: dict[str, list[dict]] = {}
    for market in markets:
        events.setdefault(market["event_ticker"], []).append(market)
    return events


def _first(rows: list[dict], field: str):
    return min((r[field] for r in rows if r.get(field)), default=None)


def build_snapshot(
    client: Client,
    sleeve: str,
    captured_at: str,
    *,
    want_orderbook: bool = False,
    keep_raw: bool = False,
    generator: str = "kiix.snapshot",
) -> dict:
    """Discover, fetch, normalize and classify one sleeve's markets."""
    alerts = AlertLog()
    expected = registry.by_ticker(sleeve)

    discovered = discover_series(client, CATEGORIES)
    selected = [t for t in expected if t in discovered]

    for ticker in expected:
        if ticker not in selected:
            alerts.critical(
                "series_not_discovered",
                f"{ticker} did not appear under categories {list(CATEGORIES)}; "
                "likely renamed or delisted",
                series_ticker=ticker,
            )

    series_out: list[dict] = []
    markets_out: list[dict] = []
    orderbooks: dict[str, dict] = {}

    for ticker in selected:
        spec = expected[ticker]
        detail = series_detail(client, ticker)
        raw_markets = open_markets(client, ticker)
        markets = [
            normalize_market(m, ticker, captured_at, keep_raw=keep_raw)
            for m in raw_markets
        ]

        if not markets:
            alerts.warning(
                "no_open_markets",
                f"{ticker} discovered but has no open markets in this snapshot",
                series_ticker=ticker,
            )

        all_events = _event_rows(markets)
        if spec.event_suffix:
            kept = {k: v for k, v in all_events.items() if k.endswith(spec.event_suffix)}
            skipped = sorted(set(all_events) - set(kept))
            if not kept:
                alerts.critical(
                    "no_matching_event",
                    f"{ticker} has open events {sorted(all_events)} but none end in "
                    f"{spec.event_suffix!r}; the sleeve's event may have been renamed",
                    series_ticker=ticker,
                )
        else:
            kept, skipped = all_events, []
        markets = [m for m in markets if m["event_ticker"] in kept]

        events_out = []
        structures = set()
        for event_ticker, rows in sorted(kept.items()):
            classification = classify_ladder(rows)
            structures.add(classification["structure"])
            _alert_on_structure(alerts, ticker, event_ticker, spec, classification)
            events_out.append(
                {
                    "event_ticker": event_ticker,
                    "close_time": _first(rows, "close_time"),
                    "expiration_time": _first(rows, "expiration_time"),
                    "rules_primary": next(
                        (
                            r.get("rules_primary")
                            for r in raw_markets
                            if r.get("event_ticker") == event_ticker
                            and r.get("rules_primary")
                        ),
                        None,
                    ),
                    "diagnostics": event_diagnostics(rows, classification),
                    "tickers": [m["ticker"] for m in rows],
                }
            )

        series_out.append(
            {
                "series_ticker": ticker,
                "sleeve": spec.sleeve,
                "role": spec.role,
                "tenor": spec.tenor,
                "stitch_group": spec.stitch_group,
                "information_horizon": spec.information_horizon,
                "expected_structure": spec.expected_structure,
                "observed_structures": sorted(structures),
                "event_suffix": spec.event_suffix,
                "events_skipped": skipped,
                "fit_excluded": any(not e["diagnostics"]["fittable"] for e in events_out),
                "title": detail.get("title"),
                "category": detail.get("category"),
                "frequency": detail.get("frequency"),
                "settlement_sources": detail.get("settlement_sources"),
                "contract_terms_url": detail.get("contract_terms_url"),
                "last_updated_ts": detail.get("last_updated_ts"),
                "events": events_out,
            }
        )
        markets_out.extend(markets)

        if want_orderbook:
            for market in markets:
                orderbooks[market["ticker"]] = orderbook(client, market["ticker"])

    return {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "sleeve": sleeve,
            "captured_at": captured_at,
            "categories": list(CATEGORIES),
            "generator": generator,
            "idempotency_key": ["ticker", "captured_at"],
            "information_horizon": registry.horizon_for_sleeve(sleeve),
            "stitch_groups": registry.stitch_groups(sleeve),
            "orderbook_included": want_orderbook,
            "raw_included": keep_raw,
        },
        "discovery": {
            "categories": list(CATEGORIES),
            "n_series_discovered": len(discovered),
            # ticker -> the categories it was found under, so a recategorization
            # shows up as a diff between snapshots.
            "series_categories": discovered,
            "expected": sorted(expected),
            "selected": selected,
        },
        "alerts": alerts.items,
        "series": series_out,
        "markets": markets_out,
        "orderbooks": orderbooks or None,
    }


def _alert_on_structure(
    alerts: AlertLog,
    ticker: str,
    event_ticker: str,
    spec: registry.SeriesSpec,
    classification: dict,
) -> None:
    """Fail closed on structure: nothing defaults to the partitioned path."""
    structure = classification["structure"]
    why = "; ".join(classification["reasons"])

    if structure == "unknown":
        alerts.critical(
            "unknown_structure",
            f"{event_ticker} could not be classified ({why}); excluded from fitting",
            series_ticker=ticker,
            event_ticker=event_ticker,
        )
    elif structure == "barrier":
        alerts.warning(
            "barrier_structure",
            f"{event_ticker} prices a running extremum, not a terminal value ({why}); "
            "excluded from fitting",
            series_ticker=ticker,
            event_ticker=event_ticker,
        )
    elif structure == "cumulative":
        alerts.warning(
            "cumulative_structure",
            f"{event_ticker} reads as a survival function ({why}); needs differencing "
            "before fitting, which is not implemented yet",
            series_ticker=ticker,
            event_ticker=event_ticker,
        )

    # "none" is not a parse failure on a categorical ladder: those outcomes have
    # no strikes by construction.
    parsed = sorted(
        {m for m in classification.get("strike_sources", []) if m not in ("api", "none")}
    )
    if parsed:
        alerts.warning(
            "parsed_strikes",
            f"{event_ticker} strikes came from {parsed} rather than the API's numeric "
            "fields; a display-format change would silently reshape this ladder",
            series_ticker=ticker,
            event_ticker=event_ticker,
        )

    if structure != spec.expected_structure and structure != "unknown":
        alerts.critical(
            "structure_changed",
            f"{event_ticker} classified as {structure} but the registry expects "
            f"{spec.expected_structure}; the exchange changed this ladder's shape",
            series_ticker=ticker,
            event_ticker=event_ticker,
        )
