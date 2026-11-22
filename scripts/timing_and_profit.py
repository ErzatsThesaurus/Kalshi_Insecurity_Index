"""When did Kalshi's price collapse onto the winner, how volatile was it, and what would a start-of-night buy have earned?

    python scripts/timing_and_profit.py

Uses every good snapshot (2026-11-03 21:19 UTC onward) and data/winners/winners_reference.csv.
Writes reports/timing_races.csv (one row per race, map-ready), reports/collapse_curve.png.
Prices ignore Kalshi fees and the bid/ask depth: buys are assumed filled at the quoted yes_ask.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from midterms import data as D, metrics as M, races as R  # noqa: E402

THR = 0.95  # "collapsed" = eventual winner's price >= 95c and stays there
POLLS = pd.Timestamp("2026-11-03 23:00", tz="UTC")  # first polls close (6pm ET)
ET = "America/New_York"

frames = []
for t, p in D.snapshot_dirs(ROOT):
    m = D.read_snapshot(p)
    m = m[m.series_ticker.str.startswith(("KXHOUSERACE", "HOUSEN", "SENATE", "GOVPARTY"))].copy()
    m["snap_time"] = t
    frames.append(m)
raw = pd.concat(frames, ignore_index=True)
tk = R.parse_tickers(raw)
raw = raw.merge(tk[["ticker", "kind", "key", "mparty"]], on="ticker", how="inner")
raw["p"] = M.mid_price(raw)
# finalized markets quote bid 0 / ask 1 with a stale last trade: use the settlement instead
raw.loc[raw.result == "yes", "p"] = 1.0
raw.loc[raw.result == "no", "p"] = 0.0
raw["ask"] = raw.yes_ask_dollars.where(raw.yes_ask_dollars > 0, raw.last_price_dollars)
raw["bid"] = raw.yes_bid_dollars
times = sorted(raw.snap_time.unique())
print(f"{len(times)} snapshots {times[0]} -> {times[-1]} | {raw.ticker.nunique()} party markets")

pv = raw.pivot_table(index=["kind", "key", "snap_time"], columns="mparty", values=["p", "ask", "bid"], aggfunc="first")
pv.columns = [f"{a}_{b.lower()}" for a, b in pv.columns]
pv = pv.reset_index()
pv["p_dem"] = pv.p_d.fillna(1 - pv.p_r) if "p_r" in pv else pv.p_d
w = R.load_winners(ROOT / "data/winners/winners_reference.csv")
w = w[w.win.notna()][["kind", "key", "place", "winner", "party", "win"]]
pv = pv.merge(w, on=["kind", "key"], how="inner").sort_values(["kind", "key", "snap_time"])
pv["y"] = (pv.win == "D").astype(float)
pv["p_win"] = np.where(pv.y == 1, pv.p_dem, 1 - pv.p_dem)
lg = np.log(pv.p_dem.clip(.01, .99) / (1 - pv.p_dem.clip(.01, .99)))
pv["dlogit"] = lg.groupby([pv.kind, pv.key]).diff()

rows = []
for (kind, key), g in pv.groupby(["kind", "key"]):
    g = g.dropna(subset=["p_dem"])
    if g.empty:
        continue
    t, pw = g.snap_time.to_numpy(), g.p_win.to_numpy()
    below = np.where(pw < THR)[0]
    if len(below) == 0:
        status, tc = "decided_at_start", g.snap_time.iloc[0]
    elif below[-1] == len(pw) - 1:
        status, tc = "never_collapsed", pd.NaT
    else:
        status, tc = "collapsed_during_window", g.snap_time.iloc[below[-1] + 1]
    first = g.iloc[0]
    fav_d = first.p_dem >= .5
    ask_d = first.get("ask_d", np.nan)
    ask_r = first.get("ask_r", np.nan)
    ask_fav = ask_d if fav_d else ask_r
    ask_win = ask_d if first.y == 1 else ask_r
    ask_fav = ask_fav if pd.notna(ask_fav) else (first.p_dem if fav_d else 1 - first.p_dem)
    ask_win = ask_win if pd.notna(ask_win) else (first.p_dem if first.y == 1 else 1 - first.p_dem)
    fav_won = fav_d == (first.y == 1)
    within = g[g.snap_time <= (tc if pd.notna(tc) else g.snap_time.iloc[-1])]
    rows.append(dict(kind=kind, key=key, place=first.place, winner=first.winner, party=first.party,
                     p_dem_start=first.p_dem, p_win_start=first.p_win, kalshi_fav="D" if fav_d else "R",
                     fav_correct=fav_won, status=status, t_collapse=tc,
                     min_p_win=pw.min(), led_wrong_at_some_point=bool(pw.min() < .5),
                     volatility=float(within.dlogit.abs().sum()), ask_fav=ask_fav, ask_winner_side=ask_win,
                     pnl_buy_fav=(1 - ask_fav) if fav_won else -ask_fav,
                     roi_buy_winner=(1 - ask_win) / ask_win if ask_win > 0 else np.nan))
r = pd.DataFrame(rows)
r["t_collapse_et"] = r.t_collapse.dt.tz_convert(ET).dt.strftime("%a %m-%d %H:%M")
r["hours_after_polls_close"] = (r.t_collapse - POLLS).dt.total_seconds() / 3600
r["pnl_buy_fav_roi"] = r.pnl_buy_fav / r.ask_fav

print("\n== status ==")
print(r.groupby("kind").status.value_counts().unstack(fill_value=0))
c = r[r.status == "collapsed_during_window"]
print("\n== hours after 6pm ET polls-close until price held >=95c on the winner (collapsed during window) ==")
print(c.groupby("kind").hours_after_polls_close.describe(percentiles=[.25, .5, .75]).round(1).to_string())
print("\n== earliest / latest collapses ==")
print(c.sort_values("t_collapse")[["kind", "key", "winner", "t_collapse_et", "p_win_start"]].head(5).round(2).to_string(index=False))
print(r.sort_values("t_collapse", na_position="last")[["kind", "key", "winner", "status", "t_collapse_et", "p_win_start"]].tail(10).round(2).to_string(index=False))
print("\n== most volatile (sum |change in log-odds| until collapse) ==")
print(r.sort_values("volatility", ascending=False)[["kind", "key", "winner", "p_win_start", "min_p_win", "volatility", "status", "t_collapse_et"]].head(10).round(2).to_string(index=False))
print("\n== winner behind (<50c) at some snapshot ==")
print(r[r.led_wrong_at_some_point][["kind", "key", "winner", "p_win_start", "min_p_win", "status"]].round(2).to_string(index=False))

bins = [.5, .8, .9, .95, .99, 1.0]
r["fav_price_bin"] = pd.cut(r.ask_fav, bins=bins, include_lowest=True)
b = r.groupby("fav_price_bin", observed=True).agg(n=("key", "size"), win_rate=("fav_correct", "mean"), avg_ask=("ask_fav", "mean"),
                                                  total_pnl=("pnl_buy_fav", "sum"), cost=("ask_fav", "sum"))
b["roi"] = b.total_pnl / b.cost
print("\n== buying the start-of-night favorite at the ask, 1 contract per race ==")
print(b.drop(columns="cost").round(3).to_string())
print(f"ALL: n={len(r)} pnl=${r.pnl_buy_fav.sum():.2f} on ${r.ask_fav.sum():.2f} staked, ROI {r.pnl_buy_fav.sum() / r.ask_fav.sum():.1%}")
wrong = r[~r.fav_correct]
print(f"Hindsight: buying the actual winner in the {len(wrong)} races Kalshi had wrong would have returned avg {wrong.roi_buy_winner.mean():.0%} per dollar (median {wrong.roi_buy_winner.median():.0%})")

out = ROOT / "reports"
out.mkdir(exist_ok=True)
r.drop(columns=["fav_price_bin"]).to_csv(out / "timing_races.csv", index=False, encoding="utf-8")
pv[["kind", "key", "snap_time", "p_dem"] + [c for c in ("ask_d", "ask_r", "bid_d", "bid_r") if c in pv]].dropna(subset=["p_dem"]).to_csv(out / "price_series.csv", index=False, encoding="utf-8")  # P(Dem) per race per snapshot, for the dashboard

# collapse curve: share of races whose price has settled on the winner, by clock time
settled = pd.DataFrame({"t": times})
for kind, g in r.groupby("kind"):
    settled[kind] = [(g.t_collapse <= t).sum() / len(g) for t in times]
fig, ax = plt.subplots(figsize=(7, 4))
tt = pd.to_datetime(settled.t).dt.tz_convert(ET)
for kind in ["house", "sen", "gov"]:
    ax.plot(tt, settled[kind], label=kind)
ax.axvline(POLLS.tz_convert(ET), color="k", ls="--", lw=1)
ax.set(ylabel="share of races settled (winner >= 95c and stays)", title="Kalshi collapse curve (ET)")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=tt.dt.tz))
ax.legend()
fig.tight_layout()
fig.savefig(out / "collapse_curve.png", dpi=130)
print("\nwrote reports/timing_races.csv, price_series.csv and collapse_curve.png")
