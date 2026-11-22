"""Scoring and timing metrics for binary prediction-market prices."""
from __future__ import annotations

import numpy as np
import pandas as pd


def mid_price(df: pd.DataFrame, max_spread: float = 0.20) -> pd.Series:
    """Bid/ask midpoint when both sides are quoted and the spread is tight, else the last trade."""
    bid, ask, last = df.yes_bid_dollars, df.yes_ask_dollars, df.last_price_dollars
    ok = (bid > 0) & (ask > 0) & ((ask - bid) <= max_spread)
    return ((bid + ask) / 2).where(ok, last)


def brier(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def logloss(p, y, eps: float = 1e-3) -> float:
    p, y = np.clip(np.asarray(p, float), eps, 1 - eps), np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration(p, y, bins=(0, .05, .2, .4, .6, .8, .95, 1.0)) -> pd.DataFrame:
    d = pd.DataFrame({"p": np.asarray(p, float), "y": np.asarray(y, float)})
    d["bin"] = pd.cut(d.p, bins=list(bins), include_lowest=True)
    g = d.groupby("bin", observed=True)
    return pd.DataFrame({"n": g.size(), "mean_price": g.p.mean(), "win_freq": g.y.mean()})


def collapse_time(times, p, y: int, hi: float = 0.95):
    """First snapshot from which the price stays on the correct side of `hi` (or 1-hi) until the end."""
    p = np.asarray(p, float)
    done = (p >= hi) if y == 1 else (p <= 1 - hi)
    if len(done) == 0 or not done[-1]:
        return pd.NaT
    notdone = np.where(~done)[0]
    i = notdone[-1] + 1 if len(notdone) else 0
    return times[i]


def logit_vol(p, eps: float = 0.01, min_points: int = 5) -> float:
    """Std-dev of snapshot-to-snapshot changes in log-odds (clipped away from 0 and 1)."""
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    if len(p) < min_points:
        return float("nan")
    z = np.log(p / (1 - p))
    return float(np.std(np.diff(z)))
