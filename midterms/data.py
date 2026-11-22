"""Load Kalshi midterms snapshot folders into analysis-ready tables."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

SNAP_RE = re.compile(r"^kalshi_midterms_(\d{8}T\d{6}Z)$")
# The first two snapshots have truncated, cp1252-encoded CSVs (see the data dictionary).
FIRST_GOOD = "20261103T211927Z"

KEEP = ["ticker", "event_ticker", "series_ticker", "title", "yes_sub_title", "status", "result",
        "yes_bid_dollars", "yes_ask_dollars", "last_price_dollars", "volume_fp", "open_interest_fp",
        "settlement_ts", "close_time"]
NUMERIC = ["yes_bid_dollars", "yes_ask_dollars", "last_price_dollars", "volume_fp", "open_interest_fp"]
HOUSE_TITLE = re.compile(r"^Will (?P<party>.+?) win the House race for (?P<district>[A-Z]{2}-[A-Z0-9]+)\?$")


def snapshot_dirs(root, since: str = FIRST_GOOD):
    """Complete snapshot folders (no .partial/.failed suffix) from `since` on, oldest first."""
    out = []
    for p in sorted(Path(root).iterdir()):
        m = SNAP_RE.match(p.name)
        if m and m.group(1) >= since and (p / "markets.csv").exists():
            out.append((pd.to_datetime(m.group(1), format="%Y%m%dT%H%M%SZ", utc=True), p))
    return out


def read_snapshot(path, series=None) -> pd.DataFrame:
    df = pd.read_csv(Path(path) / "markets.csv", usecols=KEEP, dtype=str,
                     encoding="utf-8", keep_default_na=False)
    if series is not None:
        df = df[df.series_ticker.isin(series)].copy()
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def build_panel(root, series=("KXHOUSERACE",), since: str = FIRST_GOOD) -> pd.DataFrame:
    """One row per (snapshot, market) for the given series, with party/district parsed for House races."""
    frames = []
    for t, p in snapshot_dirs(root, since):
        df = read_snapshot(p, series)
        df.insert(0, "snap_time", t)
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    parsed = panel.title.str.extract(HOUSE_TITLE)
    panel["party"], panel["district"] = parsed["party"], parsed["district"]
    return panel
