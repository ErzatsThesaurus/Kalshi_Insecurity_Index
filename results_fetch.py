# imports
import io
import os
import re
import time
from collections import Counter

import numpy as np
import pandas as pd
import requests
from lxml import html as lh
from pandas.plotting import table

# Header
"""
This script exits to generate a database of election winners in the 2026 midterms. 
It does so by scraping the results of the federal and gubernatorial elections from their 
respective wikipedia pages and aggragating them into a useful document for data analysis.
"""
URL = "https://en.wikipedia.org/wiki/{election}"  # loop through the election pages
UA = {"User-Agent": "NCSU Student Hobby Project"}  # User-Agent ident

# wikipedia pages to scrape
house = "2026_United_States_House_of_Representatives_elections#Open_seats"
guber = "2026_United_States_gubernatorial_elections#Race_summary"
senete = "2026_United_States_Senate_elections#Summary_results"

# Helper functions
CHECK_WORDS = (
    "check",
    "tick",
)  # words in an image's alt/src/title that mark the winner's check mark
COLOR_WORD = "green"  # only green ticks mark a winner; orange ticks (ranked-choice rounds) are ignored
CHECK = "CHECKMARK"  # text token that replaces each check-mark image
PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")  # a vote percentage such as 55.3%


def tag_checks(raw_html):
    """Replace check-mark images with the text CHECKMARK and put every candidate on its own line,
    so pd.read_html keeps both. Returns the new html and a Counter of the image names it treated as checks."""
    doc = lh.fromstring(raw_html)
    for br in doc.iter("br"):
        br.tail = "\n" + (br.tail or "")
    for el in doc.iter("li", "p"):
        el.tail = "\n" + (el.tail or "")
    found = Counter()
    for img in list(doc.iter("img")):
        name = " ".join(img.get(a, "") for a in ("alt", "src", "title")).lower()
        if any(w in name for w in CHECK_WORDS) and COLOR_WORD in name:
            found[img.get("alt") or img.get("src")] += 1
            parent, prev, tail = img.getparent(), img.getprevious(), img.tail or ""
            if prev is not None:
                prev.tail = (prev.tail or "") + CHECK + tail
            else:
                parent.text = (parent.text or "") + CHECK + tail
            parent.remove(img)
    return str(lh.tostring(doc, encoding="unicode")), found


# One candidate = text up to the ")" closing the party, plus an optional vote percentage
CAND = re.compile(r"[^()]*?\([^)]*\)(?:\s*\d{1,3}(?:\.\d+)?\s*%)?")


def parse_cell(text):
    """Split a Candidates cell into one (line, has_check, pct) entry per candidate."""
    flat = re.sub(r"\s+", " ", str(text)).strip()
    lines = [l.strip() for l in CAND.findall(flat) if l.strip()]
    if not lines:  # no "(party)" found: fall back to line breaks
        lines = [l.strip() for l in str(text).split("\n") if l.strip()]
        if (
            len(lines) == 1 and len(PCT.findall(lines[0])) > 1
        ):  # still one line: cut after each percentage
            lines = [l.strip() for l in re.split(r"(?<=%)", lines[0]) if l.strip()]
    out = []
    for l in lines:
        m = PCT.search(l)
        out.append((l, CHECK in l, float(m.group(1)) if m else None))
    return out


def clean_winner(line):
    """From the check mark to the ')' after the party -> (name, party)."""
    s = line.replace(CHECK, " ").split("\u258c")[
        -1
    ]  # drop the colour bar and anything before it
    m = re.match(r"\s*(.+?)\s*\(([^)]*)\)", s)
    return (m.group(1).strip(), m.group(2).strip()) if m else (s.strip() or None, None)


def verify(cands):
    """Winner = the line with the check. Confirm that line also has the highest percentage."""
    pcts = [p for _, _, p in cands if p is not None]
    checked = [c for c in cands if c[1]]
    name, party = clean_winner(checked[0][0]) if checked else (None, None)
    win_pct = checked[0][2] if checked else None
    if not cands:
        issue = "empty_cell"
    elif not checked:
        issue = "no_check"
    elif len(checked) > 1:
        issue = "multiple_checks"
    elif len(cands) == 1:
        issue = "ok"  # unopposed: nothing to compare against
    elif win_pct is None and not pcts:
        issue = "ok_no_pct"  # no percentages in the cell, so the highest-percent test cannot run
    elif win_pct is None:
        issue = "check_line_has_no_pct"
    elif win_pct < max(pcts):
        issue = "check_not_on_highest_pct"
    else:
        issue = "ok"
    return {
        "winner": name,
        "party": party,
        "winner_pct": win_pct,
        "max_pct": max(pcts) if pcts else None,
        "n_candidates": len(cands),
        "issue": issue,
    }


# Loop though the pages
pages = {"house": house, "guber": guber, "senete": senete}  # label -> page
TABLE_INDEX = {
    "house": list(range(17, 67)),
    "guber": [4],
    "senete": [13, 14],
}  # tables to keep on each page
SHOW_INVENTORY = (
    False  # True prints every table on each page (index, shape, first columns)
)

frames = []
check_images = Counter()
for label, page in pages.items():
    resp = requests.get(URL.format(election=page), headers=UA, timeout=30)
    resp.raise_for_status()
    html_clean, found = tag_checks(
        resp.text
    )  # check-mark images become text before pandas reads the tables
    check_images.update(found)
    tables = pd.read_html(io.StringIO(html_clean))

    if SHOW_INVENTORY:
        print(f"\n{label}: {len(tables)} tables")
        for i, t in enumerate(tables):
            print(f"  [{i}] shape={t.shape} cols={list(t.columns)[:4]}")

    for idx in TABLE_INDEX[label]:
        t = tables[idx]
        if (
            "candidates" not in str(t.columns[-1]).lower()
        ):  # guards against the table indexes shifting
            print(
                f"WARNING {label} table {idx}: last column is {t.columns[-1]!r}, not Candidates"
            )
        page_df = t.iloc[
            :, [0, -1]
        ].copy()  # keep the first column (district/state) and the last (Candidates)
        page_df.columns = ["place", "candidates"]
        page_df.insert(0, "source", label)  # remember which page each row came from
        page_df.insert(1, "table", idx)
        frames.append(page_df)
    time.sleep(1.5)  # be polite to Wikipedia between requests

df = pd.concat(frames, ignore_index=True)
# normalise place names (non-breaking spaces, footnote marks like [a], stray whitespace)
df["place"] = (
    df["place"]
    .astype(str)
    .str.replace("\xa0", " ", regex=False)
    .str.replace(r"\[.*?\]", "", regex=True)
    .str.replace(r"\s+", " ", regex=True)
    .str.strip()
)

# Races to throw out for now (still contested)
EXCLUDE = [("house", "Minnesota 1")]  # hand recount requested
drop = pd.Series(False, index=df.index)
for src, place in EXCLUDE:
    drop |= (df["source"] == src) & (df["place"] == place)
print("excluded rows:", int(drop.sum()))
df = df[~drop].reset_index(drop=True)

# Pare down to the winner, then check the check mark sits on the highest percentage
checked = pd.DataFrame([verify(parse_cell(c)) for c in df["candidates"]])
results = df[["source", "table", "place"]].join(checked)

# Print results (will likely need cleaning)
print("check images matched:", dict(check_images))
print(results.shape)
print(results.groupby("source").size())
print(results.groupby("source")["issue"].value_counts())
print(results[~results["issue"].isin(["ok", "ok_no_pct"])].head(20))

# Reference table of winners: only rows where one green check sits on the highest percentage
# Dropped here: Minnesota 1 (recount) and Louisiana 5 and 6 (runoff) show up as non-ok rows
winners = results[results["issue"].isin(["ok", "ok_no_pct"])][
    [
        "source",
        "table",
        "place",
        "winner",
        "party",
        "winner_pct",
        "n_candidates",
        "issue",
    ]
]
winners = winners.reset_index(drop=True)
dupes = winners[winners.duplicated(["source", "place"], keep=False)]
print("winners:", winners.shape, "| duplicate source+place rows:", len(dupes))

# Collapse duplicates: same place with the same winner -> keep one row.
# Same place with different winners is a conflict: print it and leave it out for review.
n_winners = (
    winners.groupby(["source", "place"])[["winner", "party"]]
    .transform(lambda c: c.nunique())
    .max(axis=1)
)
conflicts = winners[n_winners > 1]
print("conflicting duplicates (left out):", len(conflicts))
print(conflicts.sort_values(["source", "place"]))
winners = (
    winners[n_winners <= 1].drop_duplicates(["source", "place"]).reset_index(drop=True)
)
print("after collapse:", winners.shape)
print(winners.groupby("source").size())
print(dupes.sort_values(["source", "place"]).head(20))
print(winners.head(10))

os.makedirs("data/winners", exist_ok=True)
winners.to_csv("data/winners/winners_reference.csv", index=False, encoding="utf-8")
print("wrote data/winners/winners_reference.csv")

# Sanity check: unique districts (house) / states (senate, guber) at each stage
print("\nunique places per source")
print(
    pd.DataFrame(
        {
            "scraped_rows": df.groupby("source").size(),
            "unique_places": df.groupby("source")["place"].nunique(),
            "in_winners_table": winners.groupby("source")["place"].nunique(),
        }
    )
)
