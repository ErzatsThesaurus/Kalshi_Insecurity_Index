# Data sources and terms (checked 2026-11-22)

## Kalshi
Public market-data endpoints, no key needed (`api.elections.kalshi.com/trade-api/v2`). Used by `kalshi_midterms.py`.

## Winners: Wikipedia (chosen)
- Wikimedia requires every automated client to send a descriptive `User-Agent` with contact information, in the form
  `<client name>/<version> (<contact information>) <library/framework name>/<version>`, and may block clients that do not
  (https://www.mediawiki.org/wiki/Wikimedia_APIs/Access_policy, https://meta.wikimedia.org/wiki/API_Policy_Update_2024).
- `scripts/fetch_wikipedia_house.py` follows that: it requires `--contact`, fetches sequentially about 1.5 s apart, uses `maxlag`,
  honors `Retry-After`, and caches raw HTML under `data/raw/wikipedia/` (git-ignored) with a manifest of revision ids.
- Parsing the cached pages into `data/winners/house_winners.csv` is a separate step.

  @misc{ enwiki:1387082932,
    author = "{Wikipedia contributors}",
    title = "2026 United States House of Representatives elections --- {Wikipedia}{,} The Free Encyclopedia",
    year = "2026",
    url = "https://en.wikipedia.org/w/index.php?title=2026_United_States_House_of_Representatives_elections&oldid=1387082932",
    note = "[Online; accessed 22-November-2026]"
  }
  @misc{ enwiki:1386990454,
    author = "{Wikipedia contributors}",
    title = "2026 United States gubernatorial elections --- {Wikipedia}{,} The Free Encyclopedia",
    year = "2026",
    url = "https://en.wikipedia.org/w/index.php?title=2026_United_States_gubernatorial_elections&oldid=1386990454",
    note = "[Online; accessed 22-November-2026]"
  }
  @misc{ enwiki:1387097317,
    author = "{Wikipedia contributors}",
    title = "2026 United States Senate elections --- {Wikipedia}{,} The Free Encyclopedia",
    year = "2026",
    url = "https://en.wikipedia.org/w/index.php?title=2026_United_States_Senate_elections&oldid=1387097317",
    note = "[Online; accessed 22-November-2026]"
  }