"""Ground truth: Kalshi's own settlement results, optionally cross-checked against an external winners file.

External file: data/winners/house_winners.csv with columns  district,winner_party  (e.g. `WY-AL,Republican`).
"""
from __future__ import annotations

import pandas as pd


def norm_party(s: pd.Series) -> pd.Series:
    m = {"d": "democratic", "democrat": "democratic", "democratic party": "democratic",
         "r": "republican", "republican party": "republican", "gop": "republican",
         "i": "independent", "ind": "independent"}
    s = s.astype(str).str.strip().str.lower()
    return s.map(lambda x: m.get(x, x))


def kalshi_outcomes(panel: pd.DataFrame) -> pd.Series:
    """ticker -> 1/0 for markets finalized as of the last snapshot in the panel."""
    last = panel[panel.snap_time == panel.snap_time.max()]
    fin = last[(last.status == "finalized") & last.result.isin(["yes", "no"])]
    return fin.set_index("ticker").result.map({"yes": 1, "no": 0}).rename("y")


def external_outcomes(panel: pd.DataFrame, winners_csv) -> pd.Series:
    w = pd.read_csv(winners_csv)
    w["winner_party"] = norm_party(w.winner_party)
    t = panel.drop_duplicates("ticker")[["ticker", "district", "party"]].dropna()
    t["party"] = norm_party(t.party)
    m = t.merge(w[["district", "winner_party"]], on="district", how="inner")
    m["y"] = (m.party == m.winner_party).astype(int)
    return m.set_index("ticker").y


def crosscheck(kalshi: pd.Series, external: pd.Series) -> pd.DataFrame:
    """Markets where both sources have an outcome but disagree."""
    j = pd.concat([kalshi.rename("kalshi"), external.rename("external")], axis=1, join="inner")
    return j[j.kalshi != j.external]
