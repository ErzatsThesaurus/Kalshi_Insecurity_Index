"""Build dashboard/index.html (self-contained) from reports/timing_races.csv + dashboard/states_paths.json.

    python dashboard/build_dashboard.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from midterms import data as D, races as R  # noqa: E402

geo = json.loads((ROOT / "dashboard/states_paths.json").read_text())
abbr = R.ST
geo["height"], geo["width"], geo["x0"] = 620, 1045, -70  # room for Alaska (starts left of 0) and the Florida keys
for s in geo["states"]:
    s["abbr"] = abbr.get(s["name"], "DC")

races = pd.read_csv(ROOT / "reports/timing_races.csv")
winners = R.load_winners(ROOT / "data/winners/winners_reference.csv")


def clean(v):
    if isinstance(v, (float, np.floating)) and np.isnan(v):
        return None
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, np.generic):
        return v.item()
    return v


data = {"sen": {}, "gov": {}, "house": {}}
for kind in ("sen", "gov", "house"):
    for w in winners[winners.kind == kind].itertuples():
        data[kind][w.key] = {"state": w.key, "race": w.place, "winner": w.winner, "party": w.party, "dem_won": bool(w.win == "D"), "scored": False}
    for r in races[races.kind == kind].itertuples():
        data[kind][r.key].update({k: clean(getattr(r, k)) for k in
                                  ["p_dem_start", "kalshi_fav", "fav_correct", "status", "t_collapse_et",
                                   "min_p_win", "pnl_buy_fav", "roi_buy_winner", "volatility"]}, scored=True)

districts = json.loads((ROOT / "dashboard/lazyGovWorkers/districts_paths.json").read_text())
missing = [d["key"] for d in districts if d["key"] not in data["house"]]
print("districts without a winner row:", missing)

ps = pd.read_csv(ROOT / "reports/price_series.csv", parse_dates=["snap_time"])
times = sorted(ps.snap_time.unique())
tidx = {t: i for i, t in enumerate(times)}
series = {"house": {}, "sen": {}, "gov": {}}
askd = {"house": {}, "sen": {}, "gov": {}}
askr = {"house": {}, "sen": {}, "gov": {}}
bidd = {"house": {}, "sen": {}, "gov": {}}
bidr = {"house": {}, "sen": {}, "gov": {}}
for (kind, key), g in ps.groupby(["kind", "key"]):
    arr, ad, ar, bd, br = ([None] * len(times) for _ in range(5))
    nan = pd.Series(np.nan, index=g.index)
    for t, p, d, r, x, y in zip(g.snap_time, g.p_dem, g.get("ask_d", nan), g.get("ask_r", nan), g.get("bid_d", nan), g.get("bid_r", nan)):
        i = tidx[t]
        bd[i] = None if pd.isna(x) else round(float(x), 3)
        br[i] = None if pd.isna(y) else round(float(y), 3)
        arr[i] = round(float(p), 3)
        ad[i] = None if pd.isna(d) else round(float(d), 3)
        ar[i] = None if pd.isna(r) else round(float(r), 3)
    series[kind][key], askd[kind][key], askr[kind][key], bidd[kind][key], bidr[kind][key] = arr, ad, ar, bd, br
timing = {"times": [pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ") for t in times], "series": series, "askD": askd, "askR": askr, "bidD": bidd, "bidR": bidr}

# candidate names per race side, from Kalshi's own market labels (first and last snapshot)
names = {"house": {}, "sen": {}, "gov": {}}
snaps = D.snapshot_dirs(ROOT)
for _, sp in (snaps[0], snaps[-1]):
    for r in R.parse_tickers(D.read_snapshot(sp)).itertuples():
        names[r.kind].setdefault(r.key, {}).setdefault(r.mparty, r.cand)
print("races with both candidate names:", {k: sum(len(v) == 2 for v in d.values()) for k, d in names.items()})

html = (ROOT / "dashboard/template.html").read_text(encoding="utf-8")
payload = json.dumps({"geo": geo, "data": data, "districts": districts, "timing": timing, "names": names}, separators=(",", ":"))
(ROOT / "dashboard/index.html").write_text(html.replace("__PAYLOAD__", payload), encoding="utf-8")
print("wrote dashboard/index.html", round(len(payload) / 1e3), "KB payload;",
      {k: f"{sum(v['scored'] for v in d.values())}/{len(d)} scored" for k, d in data.items()})
