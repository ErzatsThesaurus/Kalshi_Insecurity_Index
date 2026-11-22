"""Build the compact analysis panel from the raw snapshot folders (needs the folders next to this repo).

    python scripts/build_dataset.py [--series KXHOUSERACE ...]

Writes data/derived/house_race_panel.csv: one row per (snapshot, market).
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from midterms.data import FIRST_GOOD, build_panel  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--series", nargs="+", default=["KXHOUSERACE"])
ap.add_argument("--since", default=FIRST_GOOD)
ap.add_argument("--out", default=str(ROOT / "data/derived/house_race_panel.csv"))
a = ap.parse_args()

panel = build_panel(ROOT, series=a.series, since=a.since)
panel.to_csv(a.out, index=False, float_format="%.4f")
print(f"{len(panel):,} rows, {panel.ticker.nunique()} markets, {panel.snap_time.nunique()} snapshots -> {a.out}")
