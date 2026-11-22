# KIIX midterms: how well did Kalshi predict the 2026 House winners?

Scrapes Kalshi's public API for 2026 midterms markets, keeps 20-minute snapshots through election night, and
scores how well the prices predicted winners and how fast they collapsed once results came in.

## Layout

| Path | What |
| --- | --- |
| `kalshi_midterms.py` | Scraper. `python kalshi_midterms.py --every 20` writes a `kalshi_midterms_<UTC time>/` snapshot folder each run (needs `requests`). |
| `test_snapshots.py` | Integrity checks across snapshot folders. |
| `midterms/` | Analysis package: `data.py` (load snapshots), `metrics.py` (Brier, log loss, calibration, collapse time, log-odds volatility), `outcomes.py` (ground truth). |
| `scripts/build_dataset.py` | Builds `data/derived/house_race_panel.csv` from the raw snapshots. |
| `scripts/first_look.py` | First look at accuracy and collapse timing; writes `reports/`. |
| `data/derived/` | Compact panel (one row per snapshot x House race market). Committed. |
| `data/winners/` | Put `house_winners.csv` here (`district,winner_party`) to score against an external source instead of Kalshi's own results. |
| `support_data/` | Turnout reference CSVs (2022 actual, 2026 estimate). |
| `reports/` | Outputs of the analysis scripts. |

The raw snapshot folders (about 65 MB each, 72 of them) are **not** in git (see `.gitignore`). `data/derived/` is enough to re-run the analysis.

## Reproduce

```
pip install -r requirements.txt
python scripts/build_dataset.py     # only with the raw snapshot folders present
python scripts/first_look.py
```

## Data notes

- Snapshots `...T205944Z` and `...T210920Z` have truncated CSVs and are skipped (`midterms/data.py: FIRST_GOOD`).
- A run builds in `<name>.partial` and is renamed on success, so unsuffixed folders are complete.
- Full field-by-field data dictionary: https://claude.ai/artifact/J7u9J15KGrD1BTne14Hq7r
- Winner markets are `KXHOUSERACE` (one market per party per district, e.g. `Will Democratic win the House race for WY-AL?`).

## Status

See `reports/first_look.md`. Outcomes currently come from Kalshi's settlement results, which cover only the markets finalized by
2026-11-04 21:12 UTC, so close races are under-represented until an external winners file is added.
