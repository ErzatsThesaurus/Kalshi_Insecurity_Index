"""Score start-of-night Kalshi prices (House, Senate, governor) against Wikipedia winners.

    python scripts/score_start_of_night.py [snapshot_folder_name]

Default snapshot = first good one (2026-11-03 21:19 UTC, before any polls closed).
Reads data/winners/winners_reference.csv; writes reports/start_of_night_races.csv and reports/start_of_night_calibration.png.
Forecast per race = P(Democratic win) from the D market (or 1 - R market if only R exists). Independent/other winners are skipped.
"""
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from midterms import data as D, metrics as M  # noqa: E402

ST = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
      "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
      "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
      "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
      "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
      "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
      "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
      "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
      "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
      "Wisconsin": "WI", "Wyoming": "WY"}
PARTY = {"democrat": "D", "democratic": "D", "democrats": "D", "democratics": "D", "republican": "R", "republicans": "R"}


def party_letter(s):
    s = str(s).lower()
    if s.startswith(("democrat", "dfl")):
        return "D"
    if s.startswith("republican"):
        return "R"
    return None


def norm_district(d):  # NH-1 -> NH-01
    st, n = d.split("-")
    return f"{st}-{int(n):02d}" if n.isdigit() else f"{st}-{n}"


# ---- winners -> key + party letter
w = pd.read_csv(ROOT / "data/winners/winners_reference.csv")
w["win"] = w.party.map(party_letter)


def key(r):
    if r.source == "house":
        m = re.match(r"(.+?) (?:at-large|(\d+))$", r.place)
        return f"{ST[m.group(1)]}-{int(m.group(2)):02d}" if m.group(2) else f"{ST[m.group(1)]}-AL"
    return ST[re.sub(r"\s*\(.*$", "", r.place)]


w["key"] = w.apply(key, axis=1)
w["kind"] = w.source.map({"house": "house", "guber": "gov", "senete": "sen"})

# ---- markets from one snapshot
snaps = D.snapshot_dirs(ROOT)
t0, path = next(((t, p) for t, p in snaps if len(sys.argv) < 2 or p.name == sys.argv[1]))
m = D.read_snapshot(path)
m["p"] = M.mid_price(m)
rows = []
for r in m.itertuples():
    t = r.title
    if r.series_ticker == "KXHOUSERACE" or r.series_ticker.startswith("HOUSEN"):
        x = re.match(r"^Will (?:a |an |the )?(.+?) win the House race for ([A-Z]{2}-[A-Z0-9]+)\?$", t)
        if x:
            rows.append(("house", norm_district(x.group(2)), party_letter(x.group(1)), r.p, r.ticker, r.yes_sub_title))
    elif r.series_ticker.startswith("SENATE") and r.event_ticker.endswith("-26"):
        x = re.match(r"^Will (\w+) win the Senate race in (.+)\?$", t)
        if x and x.group(2) in ST:
            rows.append(("sen", ST[x.group(2)], party_letter(x.group(1)), r.p, r.ticker, r.yes_sub_title))
    elif r.series_ticker.startswith("GOVPARTY") and r.event_ticker.endswith("-26"):
        x = re.match(r"^Will the (\w+) party win the governorship in (.+?)\??$", t)
        if x and x.group(2) in ST:
            rows.append(("gov", ST[x.group(2)], party_letter(x.group(1)), r.p, r.ticker, r.yes_sub_title))
mk = pd.DataFrame(rows, columns=["kind", "key", "mparty", "p", "ticker", "cand"]).dropna(subset=["mparty", "p"])
# one forecast per race: P(D wins)
d = mk[mk.mparty == "D"].groupby(["kind", "key"]).agg(p_d=("p", "first"), d_cand=("cand", "first"))
r_ = mk[mk.mparty == "R"].groupby(["kind", "key"]).agg(p_r=("p", "first"), r_cand=("cand", "first"))
f = d.join(r_, how="outer").reset_index()
f["p_dem"] = f.p_d.fillna(1 - f.p_r)

j = w.merge(f, on=["kind", "key"], how="left")
j["y"] = (j.win == "D").astype(float)
print(f"snapshot {path.name}  ({t0})")
print(f"winners {len(w)} | with a Kalshi D/R market {j.p_dem.notna().sum()} | winner not D/R {j.win.isna().sum()}")
print(j.groupby("kind").agg(winners=("key", "size"), matched=("p_dem", lambda s: s.notna().sum())))
j = j[j.p_dem.notna() & j.win.notna()].copy()
j["fav_d"] = j.p_dem > 0.5
j["correct"] = (j.fav_d == (j.y == 1)) | (j.p_dem == 0.5)

def score(g):
    return pd.Series({"n": len(g), "brier": M.brier(g.p_dem, g.y), "logloss": M.logloss(g.p_dem, g.y),
                      "accuracy": g.correct.mean(), "toss-up n (.25-.75)": ((g.p_dem > .25) & (g.p_dem < .75)).sum(),
                      "toss-up acc": g[(g.p_dem > .25) & (g.p_dem < .75)].correct.mean()})

print("\n== scores (Brier of a flat 0.5 forecast = 0.250) ==")
print(pd.concat([j.groupby("kind").apply(score), score(j).rename("all").to_frame().T]).round(4).to_string())
print("\n== calibration (all races) ==")
print(M.calibration(j.p_dem, j.y).round(3).to_string())
j["err"] = (j.p_dem - j.y).abs()
cols = ["kind", "key", "place", "winner", "party", "p_dem", "y", "d_cand", "r_cand"]
print("\n== 15 biggest misses ==")
print(j.sort_values("err", ascending=False)[cols].head(15).round(3).to_string(index=False))

out = ROOT / "reports"
out.mkdir(exist_ok=True)
j.sort_values("err", ascending=False)[cols + ["err", "correct"]].to_csv(out / "start_of_night_races.csv", index=False, encoding="utf-8")
c = M.calibration(j.p_dem, j.y)
fig, ax = plt.subplots(figsize=(5, 5))
ax.plot([0, 1], [0, 1], "k--", lw=1)
ax.scatter(c.mean_price, c.win_freq, s=c.n * 3)
ax.set(xlabel="mean P(Democratic win), start of night", ylabel="Democratic win frequency", title="Kalshi calibration (dot size = races)")
fig.tight_layout()
fig.savefig(out / "start_of_night_calibration.png", dpi=130)
print("\nwrote reports/start_of_night_races.csv and reports/start_of_night_calibration.png")
