"""Shared race helpers: state map, party parsing, winners key, and Kalshi title parsing."""
from __future__ import annotations

import re

import pandas as pd

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




def load_winners(path) -> pd.DataFrame:
    w = pd.read_csv(path)
    w["win"] = w.party.map(party_letter)

    def key(r):
        if r.source == "house":
            m = re.match(r"(.+?) (?:at-large|(\d+))$", r.place)
            return f"{ST[m.group(1)]}-{int(m.group(2)):02d}" if m.group(2) else f"{ST[m.group(1)]}-AL"
        return ST[re.sub(r"\s*\(.*$", "", r.place)]

    w["key"] = w.apply(key, axis=1)
    w["kind"] = w.source.map({"house": "house", "guber": "gov", "senete": "sen"})
    return w


def parse_tickers(m: pd.DataFrame) -> pd.DataFrame:
    """One row per ticker -> kind, key, mparty (D/R) for the House/Senate/governor party markets of the 2026 races."""
    rows = []
    for r in m.drop_duplicates("ticker").itertuples():
        t, s = r.title, r.series_ticker
        if s == "KXHOUSERACE" or s.startswith("HOUSEN"):
            x = re.match(r"^Will (?:a |an |the )?(.+?) win the House race for ([A-Z]{2}-[A-Z0-9]+)\?$", t)
            if x:
                rows.append((r.ticker, "house", norm_district(x.group(2)), party_letter(x.group(1)), r.yes_sub_title))
        elif s.startswith("SENATE") and r.event_ticker.endswith("-26"):
            x = re.match(r"^Will (\w+) win the Senate race in (.+)\?$", t)
            if x and x.group(2) in ST:
                rows.append((r.ticker, "sen", ST[x.group(2)], party_letter(x.group(1)), r.yes_sub_title))
        elif s.startswith("GOVPARTY") and r.event_ticker.endswith("-26"):
            x = re.match(r"^Will the (\w+) party win the governorship in (.+?)\??$", t)
            if x and x.group(2) in ST:
                rows.append((r.ticker, "gov", ST[x.group(2)], party_letter(x.group(1)), r.yes_sub_title))
    return pd.DataFrame(rows, columns=["ticker", "kind", "key", "mparty", "cand"]).dropna(subset=["mparty"])
