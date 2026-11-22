#!/usr/bin/env python3
"""Scrape Kalshi 2026 midterms markets via the public (no-auth) REST API.

Usage:
    pip install requests
    python kalshi_midterms.py                     # snapshot -> ./kalshi_midterms_<ts>/
    python kalshi_midterms.py --history           # also hourly candlesticks per market
    python kalshi_midterms.py --keywords senate house governor --outdir out

Outputs (in outdir):
    series.json      matched series metadata
    events.jsonl     one event per line (raw, markets nested)
    markets.csv      one row per market (union of all fields Kalshi returns)
    candles.csv      price history (only with --history)
"""
import argparse, csv, json, os, sys, time
from datetime import datetime, timezone

import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"
DEFAULT_KEYWORDS = ["midterm", "senate", "house", "governor", "congress", "blue wave",
                    "blue tsunami", "generic ballot", "speaker"]
DEFAULT_EXTRA = ["CONTROLS", "CONTROLH", "SENATE", "HOUSE", "KXSENATE", "KXHOUSE",
                 "KXBALANCEPOWERCOMBO", "KXSAMEPARTYCONGRESS"]
S = requests.Session()
S.headers["User-Agent"] = "kalshi-midterms-scraper/1.0"


def get(path, params=None, tries=6):
    last = None
    for i in range(tries):
        try:
            r = S.get(f"{BASE}{path}", params=params, timeout=30)
        except (requests.Timeout, requests.ConnectionError) as e:  # transient network failure
            last = e
            time.sleep(min(2 ** i, 30))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            last = requests.HTTPError(f"HTTP {r.status_code} for {path}")
            time.sleep(min(2 ** i, 30))
            continue
        r.raise_for_status()
        return r.json()
    raise last


def paginate(path, key, params):
    params = dict(params)
    while True:
        d = get(path, params)
        yield from d.get(key, [])
        cur = d.get("cursor")
        if not cur:
            return
        params["cursor"] = cur
        time.sleep(0.15)


def matches(s, kws):
    blob = " ".join([s.get("ticker", ""), s.get("title", ""), " ".join(s.get("tags") or [])]).lower()
    return "us-midterms-2026" in blob or any(k in blob for k in kws)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", nargs="*", default=DEFAULT_KEYWORDS)
    ap.add_argument("--category", default="Elections")
    ap.add_argument("--extra-series", nargs="*", default=DEFAULT_EXTRA,
                    help="series tickers always included (control/seat-count markets use legacy tickers)")
    ap.add_argument("--history", action="store_true", help="fetch candlesticks for every market")
    ap.add_argument("--period", type=int, default=60, choices=[1, 60, 1440], help="candle minutes")
    ap.add_argument("--since", default="2026-01-01", help="history start date (YYYY-MM-DD)")
    ap.add_argument("--outdir")
    ap.add_argument("--every", type=float, help="repeat every N minutes (new snapshot folder each run)")
    a = ap.parse_args()
    if a.every:
        while True:
            t = time.time()
            try:
                run(a)
            except Exception as e:  # keep looping through transient failures
                print(f"run failed: {e}", file=sys.stderr)
            time.sleep(max(0, a.every * 60 - (time.time() - t)))
    else:
        run(a)


def run(a):

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = a.outdir or f"kalshi_midterms_{ts}"
    out = final + ".partial"
    os.makedirs(out, exist_ok=True)
    kws = [k.lower() for k in a.keywords]

    # 1. discover series
    all_series = list(paginate("/series", "series", {"category": a.category})) \
        if False else get("/series", {"category": a.category}).get("series", [])
    extra = {t.upper() for t in a.extra_series}
    series = [s for s in all_series if matches(s, kws) or s["ticker"].upper() in extra]
    print(f"{len(series)} of {len(all_series)} {a.category} series matched", file=sys.stderr)
    json.dump(series, open(f"{out}/series.json", "w", encoding="utf-8"), indent=1)

    # 2. events + nested markets per series (all statuses)
    markets, fields, missing = [], [], {}

    def add_market(m, series_ticker, event_title):
        m = dict(m)
        m["series_ticker"] = series_ticker
        m["event_title"] = event_title
        markets.append(m)
        fields.extend(k for k in m if k not in fields)
    with open(f"{out}/events.jsonl", "w", encoding="utf-8") as ef:
        for s in series:
            for ev in paginate("/events", "events",
                               {"series_ticker": s["ticker"], "with_nested_markets": "true", "limit": 200}):
                ef.write(json.dumps(ev) + "\n")
                nested = ev.get("markets") or []
                if not nested:
                    missing[ev["event_ticker"]] = (s["ticker"], ev.get("title"))
                for m in nested:
                    add_market(m, s["ticker"], ev.get("title"))
            print(f"  {s['ticker']}: {len(markets)} markets so far", file=sys.stderr)

    # events that came back without nested markets: fetch them by event_ticker
    tickers = list(missing)
    for i in range(0, len(tickers), 10):
        batch = tickers[i:i + 10]
        for m in paginate("/markets", "markets", {"event_ticker": ",".join(batch), "limit": 1000}):
            st, et = missing.get(m.get("event_ticker"), (m.get("series_ticker", ""), None))
            add_market(m, st, et)
    if tickers:
        got = len({m["event_ticker"] for m in markets} & set(tickers))
        print(f"fallback: {got}/{len(tickers)} events without nested markets now have markets", file=sys.stderr)

    with open(f"{out}/markets.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(markets)
    print(f"wrote {len(markets)} markets -> {out}/markets.csv", file=sys.stderr)

    # 3. optional price history
    if a.history:
        start = int(datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc).timestamp())
        end = int(time.time())
        step = {1: 60, 60: 3600, 1440: 86400}[a.period] * 4000  # stay under 10k candles
        with open(f"{out}/candles.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["market_ticker", "end_period_ts", "price_close", "price_mean", "yes_bid_close",
                        "yes_ask_close", "volume", "open_interest"])
            for i, m in enumerate(markets, 1):
                t0 = start
                while t0 < end:
                    t1 = min(t0 + step, end)
                    try:
                        d = get(f"/series/{m['series_ticker']}/markets/{m['ticker']}/candlesticks",
                                {"start_ts": t0, "end_ts": t1, "period_interval": a.period})
                    except requests.HTTPError as e:
                        print(f"  skip {m['ticker']}: {e}", file=sys.stderr)
                        break
                    for c in d.get("candlesticks", []):
                        p, yb, ya = c.get("price", {}), c.get("yes_bid", {}), c.get("yes_ask", {})
                        w.writerow([m["ticker"], c.get("end_period_ts"),
                                    p.get("close_dollars", p.get("close")), p.get("mean_dollars", p.get("mean")),
                                    yb.get("close_dollars", yb.get("close")), ya.get("close_dollars", ya.get("close")),
                                    c.get("volume_fp", c.get("volume")), c.get("open_interest_fp", c.get("open_interest"))])
                    t0 = t1
                    time.sleep(0.1)
                if i % 25 == 0:
                    print(f"  history {i}/{len(markets)}", file=sys.stderr)

    os.rename(out, final)  # only complete runs become real snapshot folders
    print(f"snapshot complete: {final}", file=sys.stderr)

if __name__ == "__main__":
    main()
