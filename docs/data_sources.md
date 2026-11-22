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

## Ballotpedia (not scraped)
- The paid data product's terms say Ballotpedia content is copyrighted and licensed datasets are proprietary, with no right to share the full data sets (https://developer.ballotpedia.org/dictionaries-and-terms/terms-of-use).
- Ballotpedia sells election results as bulk files and APIs, with results for callable races typically available 1 to 2 days after the election (https://ballotpedia.org/Services).
- The Ballotpedia News republication guidelines say not to scrape the website (https://news.ballotpedia.org/?p=19970).
- Not found: the main-site terms of use or robots.txt text on automated access, so permission for scraping ballotpedia.org itself is unverified.
- Decision: do not scrape. Individual race pages can still be read by hand to spot-check results. A licensed feed would need to be requested from Ballotpedia's data team.
