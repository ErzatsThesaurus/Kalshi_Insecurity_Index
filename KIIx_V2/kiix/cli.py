"""The flags and exit semantics shared by every sleeve.

Centralized so the three sleeve invocations cannot drift apart, which matters
because one systemd template unit serves all of them:

    ExecStart=... /opt/kiix/ingest/snapshot.py --sleeve %i --strict --ping-url ${HC_PING_URL}

Exit codes:
    0   snapshot written, or nothing to do (already exists / sleeve retired)
    1   ingestion failed
    2   a critical alert fired and --strict was given
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

import requests

from . import registry
from .kalshi import Client
from .snapshot import (
    DATA_DIR,
    build_snapshot,
    is_retired,
    make_captured_at,
    retirement_marker,
    snapshot_path,
    write_snapshot,
)


def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--sleeve",
        choices=registry.SLEEVES,
        required=True,
        help="which sleeve to snapshot",
    )
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="root of the data tree")
    parser.add_argument(
        "--captured-at",
        help="override the snapshot timestamp (ISO-8601 UTC) for deterministic replay",
    )
    parser.add_argument("--orderbook", action="store_true", help="also capture full book depth")
    parser.add_argument("--keep-raw", action="store_true", help="embed the raw API payload per market")
    parser.add_argument("--flat", action="store_true", help="write to the pre-sharding flat layout")
    parser.add_argument("--summary", action="store_true", help="print the resolved ladders")
    parser.add_argument("--force", action="store_true", help="overwrite an existing snapshot file")
    parser.add_argument("--strict", action="store_true", help="exit 2 if any critical alert fired")
    parser.add_argument("--ping-url", help="Healthchecks.io URL to ping on a clean run")
    parser.add_argument(
        "--ignore-retirement",
        action="store_true",
        help="snapshot even past the information horizon",
    )
    return parser


def run(argv: list[str] | None, summary: Callable[[dict], None] | None = None) -> int:
    """The whole snapshot flow, shared by every sleeve."""
    parser = add_common_args(
        argparse.ArgumentParser(
            prog="snapshot",
            description="Snapshot a KIIX political sleeve's Kalshi ladders to JSON.",
        )
    )
    args = parser.parse_args(argv)
    sleeve = args.sleeve

    retired, horizon = is_retired(sleeve)
    if retired and not args.ignore_retirement:
        marker = retirement_marker(sleeve, args.data_dir)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            f"{sleeve} retired at information_horizon {horizon}\n", encoding="utf-8"
        )
        print(
            f"{sleeve} is past its information horizon ({horizon}); wrote {marker} "
            "and captured nothing"
        )
        return 0

    captured_at = make_captured_at(args.captured_at)
    out_path = snapshot_path(sleeve, captured_at, args.data_dir, shard=not args.flat)
    if out_path.exists() and not args.force:
        print(f"snapshot already exists, nothing written: {out_path}")
        return 0

    try:
        snapshot = build_snapshot(
            Client(),
            sleeve,
            captured_at,
            want_orderbook=args.orderbook,
            keep_raw=args.keep_raw,
            generator="ingest/snapshot.py",
        )
    except Exception as exc:  # noqa: BLE001 - one failure mode for the timer
        print(f"ingest failed for sleeve={sleeve}: {exc}", file=sys.stderr)
        return 1

    write_snapshot(out_path, snapshot, sleeve, args.data_dir)
    print(
        f"wrote {out_path} ({len(snapshot['markets'])} markets, "
        f"{len(snapshot['alerts'])} alerts)"
    )
    if args.summary and summary:
        summary(snapshot)

    criticals = [a for a in snapshot["alerts"] if a["level"] == "critical"]
    for alert in criticals:
        print(f"CRITICAL {alert['kind']}: {alert['detail']}", file=sys.stderr)

    # A critical alert starves the dead-man's switch on purpose: the run failing
    # and Healthchecks going quiet are two independent signals of the same fault.
    if args.ping_url and not criticals:
        try:
            requests.get(args.ping_url, timeout=10)
        except Exception as exc:  # noqa: BLE001 - a missed ping must not fail ingest
            print(f"healthcheck ping failed: {exc}", file=sys.stderr)

    if criticals and args.strict:
        return 2
    return 0


def print_summary(snapshot: dict) -> None:
    """Structure-aware ladder summary, valid for bracket and categorical sleeves."""
    meta, disc = snapshot["meta"], snapshot["discovery"]
    print(f"sleeve {meta['sleeve']} @ {meta['captured_at']}")
    print(
        f"discovered {disc['n_series_discovered']} series in "
        f"{'+'.join(disc['categories'])}; "
        f"selected {', '.join(disc['selected']) or '(none)'}"
    )

    by_event: dict[str, list[dict]] = {}
    for market in snapshot["markets"]:
        by_event.setdefault(market["event_ticker"], []).append(market)

    for series in snapshot["series"]:
        flag = " [FIT EXCLUDED]" if series["fit_excluded"] else ""
        print(
            f"\n{series['series_ticker']}  ({series['tenor']}, {series['role']}, "
            f"{'/'.join(series['observed_structures']) or 'no events'}){flag}"
        )
        for event in series["events"]:
            diag = event["diagnostics"]
            quotes, geom = diag["quotes"], diag["geometry"]
            print(f"  {event['event_ticker']}  closes {event['close_time']}")
            print(
                f"    {quotes['n_markets']} markets, {quotes['n_two_sided']} two-sided, "
                f"sum {quotes['ladder_sum_mid_cents']}c, OI {quotes['total_open_interest']:.0f}"
            )
            if geom:
                print(
                    f"    strikes {geom['strike_range']}, spacing {geom['spacing_min']}"
                    f"-{geom['spacing_max']} (uniform={geom['spacing_uniform']}), "
                    f"point_masses={geom['all_point_masses']}, "
                    f"open tails L={geom['has_open_lower']} U={geom['has_open_upper']}, "
                    f"effective tails={geom['n_effective_tails']}"
                )
            rows = sorted(
                by_event.get(event["event_ticker"], []),
                key=lambda m: (m["floor_strike"] is None, m["floor_strike"] or 0),
            )
            for market in rows:
                price = f"{market['mid']:>5.1f}c" if market["mid"] is not None else "   --"
                note = f"  ({market['one_sided_reason']})" if market["one_sided_reason"] else ""
                print(
                    f"      {(market['yes_sub_title'] or market['ticker']):<18} {price}"
                    f"  bid/ask {market['yes_bid']}/{market['yes_ask']}{note}"
                )

    if snapshot["alerts"]:
        print("\nALERTS")
        for alert in snapshot["alerts"]:
            print(f"  [{alert['level']}] {alert['kind']}: {alert['detail']}")
