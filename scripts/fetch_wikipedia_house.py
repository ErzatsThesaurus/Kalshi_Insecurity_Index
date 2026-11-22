#!/usr/bin/env python3
"""Cache the raw Wikipedia pages for the 2026 US House elections. Fetch only, no parsing.

Run it on a machine with internet access (the sandbox/VM used for analysis cannot reach Wikipedia):

    python scripts/fetch_wikipedia_house.py --contact you@example.com
    python scripts/fetch_wikipedia_house.py --contact https://github.com/<you>/<repo>

Wikimedia requires every automated client to send a descriptive User-Agent with contact information
(<client name>/<version> (<contact>) <library>/<version>) and may block generic ones like python-requests.
--contact is therefore required and is never hard-coded. Requests are sequential, about 1.5 s apart,
use maxlag, and honor Retry-After. Output: data/raw/wikipedia/<page>.html plus manifest.json (page, revid, fetched_at).
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "https://en.wikipedia.org/w/api.php"
BASE = "2026_United_States_House_of_Representatives_elections"
STATES = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida",
          "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
          "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska",
          "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
          "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas",
          "Utah", "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming"]
VERSION = "0.1"


def user_agent(contact: str) -> str:
    if not ("@" in contact or contact.startswith("http")):
        sys.exit("--contact must be an email address or a URL (Wikimedia User-Agent policy)")
    return f"KIIXMidtermsResearch/{VERSION} ({contact}) python-requests/{requests.__version__}"


def fetch_page(session, page: str, tries: int = 5) -> dict:
    params = {"action": "parse", "page": page, "prop": "text|revid", "format": "json", "formatversion": 2,
              "redirects": 1, "maxlag": 5}
    for i in range(tries):
        r = session.get(API, params=params, timeout=60)
        if r.status_code in (429, 503):
            time.sleep(min(float(r.headers.get("Retry-After", 2 ** i * 5)), 120))
            continue
        r.raise_for_status()
        d = r.json()
        err = d.get("error")
        if err and err.get("code") == "maxlag":
            time.sleep(min(2 ** i * 5, 120))
            continue
        if err:
            raise RuntimeError(f"{page}: {err.get('code')}: {err.get('info')}")
        return d["parse"]
    raise RuntimeError(f"{page}: gave up after {tries} tries")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contact", required=True, help="email or URL for the User-Agent")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data/raw/wikipedia"))
    ap.add_argument("--refresh", action="store_true", help="re-fetch pages already cached")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    mpath = out / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}
    s = requests.Session()
    s.headers["User-Agent"] = user_agent(a.contact)

    pages = [BASE] + [f"{BASE}_in_{st.replace(' ', '_')}" for st in STATES]
    failed = []
    for page in pages:
        f = out / f"{page}.html"
        if f.exists() and not a.refresh:
            continue
        try:
            p = fetch_page(s, page)
        except Exception as e:  # keep going; report at the end
            print(f"FAILED {page}: {e}", file=sys.stderr)
            failed.append(page)
            time.sleep(a.delay)
            continue
        f.write_text(p["text"], encoding="utf-8")
        manifest[page] = {"revid": p.get("revid"), "title": p.get("title"),
                          "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "url": f"https://en.wikipedia.org/wiki/{page}"}
        mpath.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        print(f"ok {page} (rev {p.get('revid')}, {len(p['text']):,} chars)", file=sys.stderr)
        time.sleep(a.delay)
    print(f"{len(pages) - len(failed)}/{len(pages)} pages cached in {out}", file=sys.stderr)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
