# KIIX midterms: how well did Kalshi predict the 2026 midterm winners?

## View the dashboard: View analysis, strategies, and place bets.
https://erzatsthesaurus.github.io/Kalshi_Insecurity_Index/

This project is a working simulator of and analysis of Kalshi's prediction markets
during the 2026 midterm elections in the United States. The data the simulations
and analysis is based on comes from Kalshi's rest API during the election night
and continuing through the following day. Snapshots were taken every 2o minutes
of each event market tied to the election of congress as well as the gubernatorial
elections. This data base is somewhat large and not included in the repo.
## The HTML dashboard is structured as follows:
# Timing:
The time series map shows the confidence of each race level Kalshi market. The
higher confidence in the outcome the market has the higher the price for the
winner's buy price, topping out in the 95¢+ band. Analysis of the time series
can be viewed in the page as well. Race level analysis will appear on mouse
hover-over and a best buy analysis also displayed. The best buy is calculated
with perfect knowledge of outcome and the profit show is based on ~$5 buy of 
the winner.
# Profit
Simulations are run with a given budget and max bet size. The fist tab runs a
simulator where the user can make picks in any congressional and/or gubernatorial
race and see their P/L evolve over the night.
The strategies tab shows multiple predefined strategies including party line
bulls, ideal trader, and hedged portfolio.
# Results
This tab contains brief overall analysis of election night and citations.
# This build was finalized on Sunday 11/22/26 and some races with Kalshi data have not been finalized.
## Layout

| Path | What |
| --- | --- |
| `kalshi_midterms.py` | Scraper. `python kalshi_midterms.py --every 20` writes a `kalshi_midterms_<UTC time>/` snapshot folder each run (needs `requests`). |
| `test_snapshots.py` | Integrity checks across snapshot folders. |
| `midterms/` | Analysis package: `data.py` (load snapshots), `metrics.py` (Brier, log loss, calibration, collapse time, log-odds volatility), `outcomes.py` (ground truth). |
| `scripts/build_dataset.py` | Builds `data/derived/house_race_panel.csv` from the raw snapshots. |
| `scripts/fetch_wikipedia_house.py` | Caches raw Wikipedia pages for the 2026 House elections (needs `--contact`; run where Wikipedia is reachable). |
| `scripts/first_look.py` | First look at accuracy and collapse timing; writes `reports/`. |
| `data/derived/` | Compact panel (one row per snapshot x House race market). Committed. |
| `results_fetch.py` | Scrapes the certified winners (House, Senate, governor) from Wikipedia into `data/winners/winners_reference.csv`. |
| `data/winners/` | `winners_reference.csv`: 503 rows (House 432, governor 36, Senate 35). Minnesota 1 is excluded (recount) and Louisiana 5 and 6 have no winner yet (runoff). |
| `midterms/races.py` | Shared helpers: state names, district keys, winners loader, Kalshi ticker parsing. |
| `scripts/score_start_of_night.py` | Scores start-of-night prices against the winners; writes `reports/start_of_night_*`. |
| `scripts/timing_and_profit.py` | Collapse times, price series and per-race timing; writes `reports/timing_races.csv` and `reports/price_series.csv`. |
| `dashboard/` | Interactive dashboard: `index.html` (self-contained, open it in a browser), built by `build_dashboard.py` from `template.html`. |
| `support_data/` | Turnout reference CSVs (2022 actual, 2026 estimate). |
| `reports/` | Outputs of the analysis scripts. |

The raw snapshot folders (about 65 MB each, 72 of them) are **not** in git (see `.gitignore`). `data/derived/` is enough to re-run the analysis.

## Data notes

- Snapshots `...T205944Z` and `...T210920Z` have truncated CSVs and are skipped (`midterms/data.py: FIRST_GOOD`).
- A run builds in `<name>.partial` and is renamed on success, so unsuffixed folders are complete.
- Data sources and terms checks: `docs/data_sources.md`.
- Full field-by-field data dictionary: https://claude.ai/artifact/J7u9J15KGrD1BTne14Hq7r
- Winner markets are `KXHOUSERACE` (one market per party per district, e.g. `Will Democratic win the House race for WY-AL?`).

## Status

See `reports/first_look.md` for the first look, which uses Kalshi's own settlement results. The dashboard scores against the Wikipedia winners table instead. 69 House, 3 governor and 1 Senate race have no matched Kalshi market and show as unscored.

Sources: winners from Wikipedia (2026 House, Senate and gubernatorial election pages, see `docs/data_sources.md`); district maps from the U.S. Census Bureau TIGER/Line 2026 legislative geodatabase.
