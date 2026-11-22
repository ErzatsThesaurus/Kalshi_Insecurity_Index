# First look: Kalshi House race markets (provisional)

Scope: 707 `KXHOUSERACE` markets, 72 snapshots (2026-11-03 21:19 UTC to 2026-11-04 21:12 UTC). Outcomes: Kalshi
settlement results, which exist for **614 of 707** markets (the rest were unresolved at the last snapshot).
Reproduce with `python scripts/first_look.py`; numbers in `reports/first_look_summary.json`.

## Accuracy at the last snapshot before polls closed (22:59 UTC = 5:59pm ET)

| Price bucket | Markets | Mean price | Share that won | Brier |
| --- | --- | --- | --- | --- |
| <= 0.05 | 263 | 0.018 | 0% | 0.0004 |
| 0.05 to 0.20 | 35 | 0.098 | 0% | 0.0114 |
| 0.20 to 0.80 (contested) | 23 | 0.516 | 52% | 0.2225 |
| 0.80 to 0.95 | 33 | 0.905 | 100% | 0.0103 |
| >= 0.95 | 260 | 0.980 | 100% | 0.0005 |
| All | 614 | | | 0.0099 |

- The favorite won 98.7% of the time at the market level and 98.7% of 305 scored districts.
- In the 11 scored districts where the favorite priced below 0.80, the favorite won 7 (64%).
- A coin-flip scores a Brier of 0.25. The contested bucket scored 0.22, barely better than that, on only 23 markets.

## Collapse timing (91 markets not already decided before polls closed)

- 88 collapsed (price stayed >= 0.95 on the correct side to the end). Median: 4.5 hours after 6pm ET (about 10:30pm ET); middle half 2.5 to 5.2 hours.
- Settlement followed the collapse by a median of 1.5 hours.
- Log-odds volatility before collapse had no rank correlation with collapse time (-0.03, n=88).
- Winner and loser markets in the same district collapse together, so these are not independent observations.

## Caveats

1. Only finalized markets are scored, and finalized skews to easy races: 524 of 545 lopsided House markets resolved versus 23 of 66 contested ones.
2. Snapshots start at 4:19pm ET on Election Day, so this measures election-eve prices and election-night speed, not weeks-ahead forecasting.
3. 20-minute snapshots limit timing precision to about +/- 20 minutes.
4. The Brier-over-time chart (`reports/figs/brier_over_time.png`) averages only markets still active at each snapshot, so its set shrinks as markets finalize and the line is noisy.
5. No external baseline yet (polls, ratings, 2024 results), so a high hit rate in lopsided races is not evidence of skill.
