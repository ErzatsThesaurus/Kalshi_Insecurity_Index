#!/usr/bin/env python3
"""Test suite for kalshi_midterms.py snapshot folders. Stdlib only.

    python test_snapshots.py                     # all snapshots in this folder, from run 3 onward
    python test_snapshots.py --root X:\\KIIX\\midtermz --since 20261103T211927Z
    python test_snapshots.py --expected-gap 20 --movers 15

Checks
  per snapshot : files present, CSV is valid UTF-8, CSV rows == nested markets in events.jsonl,
                 no duplicate tickers, required columns, series/event ticker agreement, prices in [0,1],
                 crossed books, known statuses, control markets present, market count stable, data fresh
  per pair     : volume never decreases, updated_time never goes backward, finalized markets stay final,
                 tickers don't vanish, 2026 control probabilities sum to ~1
  across run   : snapshot cadence (gaps / missed runs)
Runs 1-2 have truncated CSVs (cp1252 crash), so --since defaults to run 3.
Exit code 1 if any FAIL. Writes test_report_<ts>.json next to the snapshots.
"""
import argparse, csv, json, os, re, statistics, sys
from collections import Counter
from datetime import datetime, timezone

csv.field_size_limit(10 ** 9)
DIR_RE = re.compile(r"^kalshi_midterms_(\d{8}T\d{6}Z)$")
REQUIRED_COLS = {"ticker", "event_ticker", "series_ticker", "title", "status", "yes_bid_dollars",
                 "yes_ask_dollars", "last_price_dollars", "volume_fp", "open_interest_fp", "updated_time"}
KNOWN_STATUS = {"active", "finalized", "closed", "determined", "inactive", "initialized", "settled",
                "unopened", "open"}
FINAL = {"finalized", "determined", "settled"}
CONTROL_SERIES = ["CONTROLH", "CONTROLS"]
RES = []


def rec(level, name, msg="", snap=None):
    RES.append({"level": level, "test": name, "snapshot": snap, "msg": msg})


def check(cond, name, msg, snap=None, level="FAIL"):
    rec("PASS" if cond else level, name, "" if cond else msg, snap)
    return cond


def fl(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def ts_of(name):
    return datetime.strptime(DIR_RE.match(name).group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def parse_iso(x):
    try:
        return datetime.fromisoformat(x.replace("Z", "+00:00"))
    except Exception:
        return None


class Snap:
    def __init__(self, root, name):
        self.name, self.path, self.time = name, os.path.join(root, name), ts_of(name)
        self.ok_csv = False
        self.rows, self.by_ticker = [], {}
        self.nested = self.n_events = 0
        self.ev_mutex = {}

    def load(self):
        files = {f: os.path.join(self.path, f) for f in ("markets.csv", "events.jsonl", "series.json")}
        missing = [f for f, p in files.items() if not os.path.exists(p)]
        if not check(not missing, "files_present", f"missing {missing}", self.name):
            return
        try:
            with open(files["markets.csv"], encoding="utf-8", newline="") as f:
                self.rows = list(csv.DictReader(f))
            self.ok_csv = True
        except UnicodeDecodeError as e:
            check(False, "csv_utf8", f"markets.csv is not valid UTF-8 ({e})", self.name)
            return
        check(True, "csv_utf8", "", self.name)
        self.by_ticker = {r["ticker"]: r for r in self.rows}
        for line in open(files["events.jsonl"], encoding="utf-8"):
            ev = json.loads(line)
            self.n_events += 1
            self.nested += len(ev.get("markets") or [])
            self.ev_mutex[ev["event_ticker"]] = ev.get("mutually_exclusive")
        try:
            check(len(json.load(open(files["series.json"], encoding="utf-8"))) > 0, "series_json", "empty", self.name)
        except Exception as e:
            check(False, "series_json", f"invalid JSON: {e}", self.name)


def check_snapshot(s, median_n):
    if not s.ok_csv:
        return
    n = s.name
    rows = s.rows
    check(len(rows) == s.nested, "rows_match_events",
          f"markets.csv has {len(rows)} rows but events.jsonl nests {s.nested} (truncated write?)", n)
    check(len(s.by_ticker) == len(rows), "no_duplicate_tickers", f"{len(rows) - len(s.by_ticker)} duplicates", n)
    cols = set(rows[0]) if rows else set()
    check(REQUIRED_COLS <= cols, "required_columns", f"missing {sorted(REQUIRED_COLS - cols)}", n)
    bad = [r["ticker"] for r in rows if r["series_ticker"] and not r["event_ticker"].startswith(r["series_ticker"])]
    check(not bad, "series_event_agree", f"{len(bad)} mismatches e.g. {bad[:3]}", n)

    out_of_range, crossed, active = [], [], 0
    for r in rows:
        for k in ("yes_bid_dollars", "yes_ask_dollars", "last_price_dollars"):
            v = fl(r.get(k))
            if v is not None and not 0 <= v <= 1:
                out_of_range.append((r["ticker"], k, v))
        b, a = fl(r.get("yes_bid_dollars")), fl(r.get("yes_ask_dollars"))
        if r["status"] == "active":
            active += 1
            if b and a and b > a + 1e-9:
                crossed.append(r["ticker"])
    check(not out_of_range, "prices_in_range", f"{len(out_of_range)} e.g. {out_of_range[:3]}", n)
    check(len(crossed) <= max(2, 0.005 * active), "crossed_books",
          f"{len(crossed)} active markets with bid > ask e.g. {crossed[:3]}", n)
    unk = Counter(r["status"] for r in rows if r["status"] not in KNOWN_STATUS)
    check(not unk, "known_statuses", f"unknown statuses {dict(unk)}", n, "WARN")

    for sr in CONTROL_SERIES:
        c = sum(1 for r in rows if r["series_ticker"] == sr)
        check(c >= 2, f"control_present_{sr}", f"only {c} markets", n)

    if median_n:
        check(abs(len(rows) - median_n) <= 0.05 * median_n, "market_count_stable",
              f"{len(rows)} markets vs median {median_n:.0f}", n, "WARN")

    ups = [t for t in (parse_iso(r.get("updated_time", "")) for r in rows) if t]
    if ups:
        age = (s.time - max(ups)).total_seconds() / 60
        check(age <= 30, "data_fresh", f"newest updated_time is {age:.0f} min before the snapshot", n, "WARN")


def check_pair(a, b):
    n = f"{a.name[-16:]} -> {b.name[-16:]}"
    if not (a.ok_csv and b.ok_csv):
        return
    vol_down, ts_back, unfinal, gone = [], [], [], []
    for t, ra in a.by_ticker.items():
        rb = b.by_ticker.get(t)
        if rb is None:
            gone.append(t)
            continue
        va, vb = fl(ra.get("volume_fp")), fl(rb.get("volume_fp"))
        if va is not None and vb is not None and vb < va - 1e-6:
            vol_down.append((t, va, vb))
        ta, tb = parse_iso(ra.get("updated_time", "")), parse_iso(rb.get("updated_time", ""))
        if ta and tb and tb < ta:
            ts_back.append(t)
        if ra["status"] in FINAL and rb["status"] not in FINAL:
            unfinal.append((t, ra["status"], rb["status"]))
    check(len(vol_down) <= 0.002 * len(a.by_ticker), "volume_monotonic",
          f"{len(vol_down)} markets lost volume, e.g. {vol_down[:3]}", n)
    check(not ts_back, "updated_time_monotonic", f"{len(ts_back)} went backward e.g. {ts_back[:3]}", n, "WARN")
    check(not unfinal, "final_stays_final", f"{len(unfinal)} e.g. {unfinal[:3]}", n)
    check(len(gone) <= 0.01 * len(a.by_ticker), "tickers_not_vanishing",
          f"{len(gone)} tickers disappeared e.g. {gone[:3]}", n, "WARN")
    new = len(set(b.by_ticker) - set(a.by_ticker))
    rec("INFO", "new_tickers", f"{new} new, {len(gone)} gone", n)


def check_control_sums(s):
    if not s.ok_csv:
        return
    by_event = {}
    for r in s.rows:
        if r["series_ticker"] in CONTROL_SERIES and r["event_ticker"].endswith("2026") and r["status"] == "active":
            by_event.setdefault(r["event_ticker"], []).append(r)
    if not by_event:
        rec("WARN", "control_sum", "no active 2026 control event found", s.name)
    for ev, ms in by_event.items():
        lp = [fl(m["last_price_dollars"]) for m in ms]
        if len(ms) >= 2 and all(v is not None for v in lp):
            tot = sum(lp)
            check(0.9 <= tot <= 1.1, f"control_sum_{ev}", f"last prices sum to {tot:.2f}", s.name, "WARN")


def check_cadence(snaps, expected):
    gaps = [(b.time - a.time).total_seconds() / 60 for a, b in zip(snaps, snaps[1:])]
    for (a, b), g in zip(zip(snaps, snaps[1:]), gaps):
        lvl = "FAIL" if g > 2 * expected else "WARN"
        check(g <= 1.5 * expected, "cadence", f"{g:.0f} min between {a.name[-16:]} and {b.name[-16:]} "
              f"(expected ~{expected:.0f}; missed run?)", b.name, lvl)
    if gaps:
        rec("INFO", "cadence_summary", f"{len(snaps)} snapshots, median gap {statistics.median(gaps):.1f} min, "
            f"max {max(gaps):.1f} min")


def movers(a, b, k):
    mv = []
    for t, rb in b.by_ticker.items():
        ra = a.by_ticker.get(t)
        if not ra:
            continue
        pa, pb = fl(ra.get("last_price_dollars")), fl(rb.get("last_price_dollars"))
        if pa is not None and pb is not None and (fl(rb.get("volume_fp")) or 0) > 0:
            mv.append((pb - pa, t, pa, pb, rb["title"][:60]))
    mv.sort(key=lambda x: -abs(x[0]))
    return mv[:k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--since", default="20261103T211927Z", help="first snapshot to test (YYYYMMDDTHHMMSSZ)")
    ap.add_argument("--expected-gap", type=float, default=20.0, help="minutes between runs")
    ap.add_argument("--movers", type=int, default=10, help="show N biggest price moves first->last")
    a = ap.parse_args()

    names = sorted(d for d in os.listdir(a.root) if DIR_RE.match(d) and DIR_RE.match(d).group(1) >= a.since)
    if len(names) < 2:
        sys.exit(f"need >=2 snapshots since {a.since} in {a.root}, found {len(names)}")
    snaps = [Snap(a.root, d) for d in names]
    for s in snaps:
        print(f"loading {s.name} ...", file=sys.stderr)
        s.load()
    good = [s for s in snaps if s.ok_csv]
    med = statistics.median(len(s.rows) for s in good) if good else 0
    for s in snaps:
        check_snapshot(s, med)
        check_control_sums(s)
    for x, y in zip(snaps, snaps[1:]):
        check_pair(x, y)
    check_cadence(snaps, a.expected_gap)

    c = Counter(r["level"] for r in RES)
    print(f"\n{len(snaps)} snapshots, {c['PASS']} passed, {c['WARN']} warnings, {c['FAIL']} failures\n")
    for lvl in ("FAIL", "WARN"):
        agg = {}
        for r in RES:
            if r["level"] == lvl:
                agg.setdefault(r["test"], []).append(r)
        for t, rs in agg.items():
            print(f"[{lvl}] {t}  x{len(rs)}  first: {rs[0]['snapshot'] or ''}: {rs[0]['msg']}")
    for r in RES:
        if r["level"] == "INFO" and r["test"] == "cadence_summary":
            print(f"[INFO] {r['msg']}")
    if len(good) >= 2 and a.movers:
        print(f"\nBiggest last-price moves, {good[0].name[-16:]} -> {good[-1].name[-16:]}:")
        for d, t, pa, pb, title in movers(good[0], good[-1], a.movers):
            print(f"  {d:+.2f}  {pa:.2f}->{pb:.2f}  {t}  {title}")

    rep = os.path.join(a.root, f"test_report_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    json.dump({"summary": dict(c), "results": [r for r in RES if r["level"] != "PASS"]}, open(rep, "w"), indent=1)
    print(f"\nreport: {rep}")
    sys.exit(1 if c["FAIL"] else 0)


if __name__ == "__main__":
    main()
