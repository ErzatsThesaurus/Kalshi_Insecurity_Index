"""First look: how well did Kalshi House-race prices predict winners, and how fast did they collapse?

    python scripts/first_look.py

Reads data/derived/house_race_panel.csv; writes reports/first_look_summary.json and reports/figs/*.png.
Outcomes come from data/winners/house_winners.csv if present (cross-checked against Kalshi), else Kalshi results.
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from midterms import metrics as M, outcomes as O  # noqa: E402

POLLS_START = pd.Timestamp("2026-11-03 23:00", tz="UTC")  # 6pm ET: first polls close (IN, KY)
panel = pd.read_csv(ROOT / "data/derived/house_race_panel.csv", parse_dates=["snap_time", "settlement_ts"])
panel["p"] = M.mid_price(panel)
panel = panel.sort_values(["ticker", "snap_time"])

summary = {"n_markets": int(panel.ticker.nunique()), "n_snapshots": int(panel.snap_time.nunique())}
y_kalshi = O.kalshi_outcomes(panel)
summary["kalshi_resolved"] = int(len(y_kalshi))
ext = ROOT / "data/winners/house_winners.csv"
if ext.exists():
    y_ext = O.external_outcomes(panel, ext)
    bad = O.crosscheck(y_kalshi, y_ext)
    summary.update(external_markets=int(len(y_ext)), disagreements=int(len(bad)))
    y = y_ext
    summary["outcome_source"] = "external winners file"
else:
    y = y_kalshi
    summary["outcome_source"] = "Kalshi settlement results (finalized markets only)"
known = set(y.index)
summary["markets_with_outcome"] = len(known)

times = pd.DatetimeIndex(panel.snap_time.unique()).sort_values()
pre_t = times[times < POLLS_START][-1]   # last snapshot before polls close
first_t = times[0]
summary["pre_poll_snapshot"] = str(pre_t)
summary["first_snapshot"] = str(first_t)

# ---- 1. accuracy at the last pre-poll snapshot -------------------------------------------------
pre = panel[(panel.snap_time == pre_t) & panel.ticker.isin(known)].set_index("ticker")
pre = pre.join(y).dropna(subset=["p", "y"])
bucket = pd.cut(pre.p, [0, .05, .2, .8, .95, 1.0], include_lowest=True,
                labels=["<=0.05", "0.05-0.2", "0.2-0.8 (contested)", "0.8-0.95", ">=0.95"])
summary["pre_poll"] = {
    "n": int(len(pre)), "brier": M.brier(pre.p, pre.y), "logloss": M.logloss(pre.p, pre.y),
    "favorite_accuracy": float(((pre.p > .5) == (pre.y == 1)).mean()),
    "brier_if_always_0.5": 0.25,
}
summary["pre_poll_by_bucket"] = {
    str(k): {"n": int(len(g)), "brier": M.brier(g.p, g.y), "mean_price": float(g.p.mean()), "win_freq": float(g.y.mean())}
    for k, g in pre.groupby(bucket, observed=True)}
cal = M.calibration(pre.p, pre.y)
summary["calibration"] = {str(k): {c: (float(v) if c != "n" else int(v)) for c, v in r.items()}
                          for k, r in cal.iterrows()}

# district-level: was the favorite (highest-priced market) the winner?
d = panel[panel.snap_time == pre_t].dropna(subset=["district", "p"]).join(y, on="ticker")
fav = d.loc[d.groupby("district").p.idxmax()]
fav = fav.dropna(subset=["y"])
summary["district_favorite"] = {"districts_scored": int(len(fav)), "favorite_won": float(fav.y.mean())}
ct = fav[(fav.p < .8)]
summary["district_favorite_contested"] = {"districts_scored": int(len(ct)), "favorite_won": float(ct.y.mean()) if len(ct) else None}

# ---- 2. Brier over time (active markets only, so post-call price lock-in is excluded) -------------
pk = panel[panel.ticker.isin(known) & (panel.status == "active")].join(y, on="ticker").dropna(subset=["p", "y"])
bt = pk.groupby("snap_time").apply(lambda g: pd.Series({"brier": M.brier(g.p, g.y), "n": len(g)}), include_groups=False)

# ---- 3. collapse time + volatility for markets that were not already decided ---------------------
rows = []
for tkr, g in panel[panel.ticker.isin(known)].groupby("ticker"):
    g = g[g.snap_time >= pre_t].dropna(subset=["p"])
    if g.empty:
        continue
    p0 = g.p.iloc[0]
    if p0 >= .95 or p0 <= .05:
        continue
    yy = int(y[tkr])
    tc = M.collapse_time(list(g.snap_time), g.p.values, yy)
    pre_collapse = g[g.snap_time <= tc] if pd.notna(tc) else g
    rows.append({"ticker": tkr, "y": yy, "p_pre": p0, "collapse": tc,
                 "hours_after_poll_close": (tc - POLLS_START).total_seconds() / 3600 if pd.notna(tc) else np.nan,
                 "vol": M.logit_vol(pre_collapse.p.values), "settled": g.settlement_ts.dropna().max() if g.settlement_ts.notna().any() else pd.NaT})
cr = pd.DataFrame(rows)
cr["settle_lag_h"] = (cr.settled - cr.collapse).dt.total_seconds() / 3600
summary["collapse"] = {
    "markets_not_decided_pre_poll": int(len(cr)),
    "collapsed_by_end": int(cr.collapse.notna().sum()),
    "median_hours_after_poll_close": float(cr.hours_after_poll_close.median()),
    "p25_p75": [float(cr.hours_after_poll_close.quantile(.25)), float(cr.hours_after_poll_close.quantile(.75))],
    "median_settle_lag_hours": float(cr.settle_lag_h.median()),
    "vol_vs_collapse_time_spearman": float(cr[["vol", "hours_after_poll_close"]].dropna().rank().corr().iloc[0, 1]),
    "winners_vs_losers_median_collapse_h": {str(k): float(v) for k, v in cr.groupby("y").hours_after_poll_close.median().items()},
}
summary["wrong_way_pre_poll"] = int(((cr.p_pre > .5) != (cr.y == 1)).sum())

# ---- figures -----------------------------------------------------------------------------------
figs = ROOT / "reports/figs"
fig, ax = plt.subplots(figsize=(5, 5))
ax.plot([0, 1], [0, 1], "--", c="grey"); ax.scatter(cal.mean_price, cal.win_freq, s=cal.n.clip(upper=400) / 3 + 20)
ax.set(xlabel="mean price at last pre-poll snapshot", ylabel="share that won", title="Calibration (House race markets)")
fig.tight_layout(); fig.savefig(figs / "calibration.png", dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(8, 4))
ax.plot(bt.index, bt.brier); ax.axvline(POLLS_START, c="grey", ls="--"); ax.set_ylabel("mean Brier (active markets)")
ax.set_title("Prediction error over election night"); fig.autofmt_xdate(); fig.tight_layout()
fig.savefig(figs / "brier_over_time.png", dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(6, 4))
ax.hist(cr.hours_after_poll_close.dropna(), bins=20); ax.set(xlabel="hours after 6pm ET until price stays >=0.95 on the right side",
                                                           ylabel="markets", title="Collapse time (not-yet-decided markets)")
fig.tight_layout(); fig.savefig(figs / "collapse_hist.png", dpi=150); plt.close(fig)

cr.to_csv(ROOT / "reports/collapse_table.csv", index=False)
(ROOT / "reports/first_look_summary.json").write_text(json.dumps(summary, indent=2, default=str))
print(json.dumps(summary, indent=2, default=str))
