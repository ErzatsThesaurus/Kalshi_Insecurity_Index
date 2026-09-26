# KIIX Politics Sleeves — Implementation Spec

2026-09-20 · @Someone

## Scope

KIIX gains three political sleeves — approval, midterm, control — folded into the existing composite index. No separate politics index.

The existing pipeline is Python/SQLite on systemd timers with idempotent upserts, a Healthchecks.io dead-man's switch, ntfy alerts, and a GitHub Pages dashboard. This work extends it. The weather sleeve's behaviour and published output must not change.

Constituents:

- Approval: `KXTRUMPAPPROVE`, `KXAPRPOTUS`
- Midterm: `KXDSENATESEATS` + `KXDSENATESEATSH` (stitched), `KXRHOUSESEATS`
- Control: `KXBALANCEPOWERCOMBO`

`KXDHOUSESEATS` is ingested but is a parity gate only, never an index constituent.

Out of scope by decision: the shutdown/fiscal sleeve, individual race markets, implied-correlation work, 2028 nomination fields, executive-order and social-post count markets, and barrier-style annual approval markets.

## Series inventory

Seven series, three structures. Strike widths marked unverified must be pulled from the API before any fitting code is written.

| Series | Structure | Underlying (unit) | Strike width | Tenor | Information horizon | Role |
| --- | --- | --- | --- | --- | --- | --- |
| `KXTRUMPAPPROVE` | Partitioned brackets | RCP approval average (pp) | UNVERIFIED — one sample strike at 39.0% | Daily, per-day event tickers | Same day | Approval constituent, anchor |
| `KXAPRPOTUS` | Partitioned brackets, flagged mutually exclusive | RCP approval average (pp) | UNVERIFIED | Weekly, settles 11:00 ET Friday | Settle date | Approval constituent, second tenor |
| `KXDSENATESEATS-27` | Brackets, open tails | D Senate seats | 1 seat, strikes 45–52 | Single event | 2026-11-03 | Midterm, stitch with `-SEATSH` |
| `KXDSENATESEATSH-27` | Brackets, open tail | D Senate seats | 1 seat, strikes 53–57 | Single event | 2026-11-03 | Stitch partner |
| `KXRHOUSESEATS-27` | Brackets, open tails | R House seats | 5 seats | Single event | 2026-11-03 | Midterm constituent |
| `KXDHOUSESEATS-27` | Brackets, open tails | D House seats | 4 seats | Single event | 2026-11-03 | Parity gate only |
| `KXBALANCEPOWERCOMBO-27FEB` | Categorical, 4 outcomes, no strikes | Chamber control combination | None | Single event | 2026-11-03 | Control constituent, entropy |

The two House ladders align only at the 218 majority line, because their widths differ. No other bucket pair maps across them.

Every price quoted in this document comes from a 2026-09-10 third-party scrape of Kalshi, not from the API. Treat all of it as structural reference, not as current data.

## Ingestion

Discover series by category on every run. Never hardcode tickers — political series churn far faster than weather series, and a namespace rename already caused one multi-day outage.

1. `GET /series?category=Politics` to enumerate series.
2. `GET /markets?series_ticker=<ticker>&status=open` per series.
3. Persist series and market rows with `first_seen` / `last_seen` so a rename surfaces as a diff plus an ntfy alert, not as silent missing data.

Capture per market per snapshot: `ticker`, `event_ticker`, `series_ticker`, `yes_bid`, `yes_ask`, `last_price`, `volume`, `open_interest`, `floor_strike`, `cap_strike`, `strike_type`, `open_time`, `close_time`, `expiration_time`, `captured_at`.

Add an `information_horizon` column at series level, distinct from `expiration_time`. Seed the midterm and control series with 2026-11-03.

Upsert idempotently on `(ticker, captured_at)` per the existing convention. Re-running a snapshot must insert no rows.

Start snapshotting before the model is finished. Two-sided quotes and book depth are not backfillable, and the window to 2026-11-03 does not repeat.

## Structure classification

Three incompatible strike shapes are live on this board and the series name does not distinguish them. Branch on `strike_type`, log the classification, and fail closed.

| Shape | How it reads | Handling |
| --- | --- | --- |
| Partitioned brackets | Disjoint, exhaustive buckets | Fit directly |
| Cumulative thresholds | "At least N" — a survival function | Difference adjacent strikes first; reject the snapshot if the differenced series is non-monotone |
| Barrier / touch | Resolves if a level is hit once in a window | Never fit — prices a running max or min, not a terminal value. Exclude the series |

An unknown or unmapped `strike_type` excludes the series and raises an alert. It must never default to the partitioned path.

## Distribution fitting

Fit an interval-censored MLE over bucket edges, reusing the weather sleeve's code path wherever it already does this.

**Price selection.** Use the mid of `yes_bid`/`yes_ask` where both sides exist. Fall back to `last_price` only with a staleness flag carrying trade age. Buckets with no two-sided quote are flagged, not silently trusted — the tails are where these ladders break.

**Normalization.** Record the raw ladder sum as an overround diagnostic before renormalizing to 1. Observed sums at the snapshot ran 101¢ to 107¢.

**Stitching.** Combine `KXDSENATESEATS` and `KXDSENATESEATSH` into one distribution and renormalize jointly. Fitting the two separately is wrong — they cover one underlying.

**Tails.** Open-ended buckets enter as censored intervals, not as point masses at the edge. This matters: `KXRHOUSESEATS` priced "Below 193" at 22¢, so tail treatment drives σ directly.

**Discreteness.** Seat counts are integers. Apply a continuity correction before fitting a continuous latent — bucket 218–222 becomes \[217.5, 222.5\].

**Output.** Emit the same three σ variants as the weather sleeve. Units differ by sleeve (percentage points against seats), so never pool or compare raw σ across sleeves. The z-score is the only common scale.

## Time normalization

The horizon is Election Day, not contract expiry. The midterm and control series settle in 2027, but their uncertainty collapses on the night of 2026-11-03 — 44 days from the date on this doc.

Normalize by days to `information_horizon`:

```latex
\tilde{\sigma}_t = \frac{\sigma_t}{\sqrt{T_t}}, \qquad T_t = \max(\text{days to horizon},\; T_{\min})
```

Store and publish both raw σ and normalized σ. Floor `T_min` at 0.5 day so the final session before the election does not divide by approximately zero.

Retire a sleeve at its horizon rather than letting T go negative. A retired sleeve leaves the composite; it does not carry its last value forward.

The approval sleeve takes no normalization. It is constant-maturity by construction, which is exactly why it is the anchor.

## Composite aggregation

Combine sleeve z-scores Stouffer-style, not as a mean:

```latex
Z_t = \frac{\sum_i w_i z_{i,t}}{\sqrt{\sum_i w_i^2}}
```

At equal weights this reduces to Σz/√k. The mean of k unit-variance z-scores has variance 1/k, so under mean(z) the composite's scale step-changes whenever a sleeve enters or leaves. Both political sleeves die on 2026-11-04, and the index would appear to spike purely from the change in k.

**Short-history problem.** The midterm and control sleeves have at most 44 days of forward history, and less if no candlestick backfill is available. A rolling z needs a baseline that does not exist yet.

Default behaviour: compute and publish each sleeve's σ from day one, but hold a sleeve out of the composite until it has `min_history` observations (config, default 30). Mark provisional sleeves on the dashboard.

Log k and the active sleeve set with every published point. The dashboard must mark constituent changes on the series.

## Data-quality gates

Each gate runs per snapshot. A failure excludes that snapshot from the index and fires the existing ntfy path. Never fit through a failed gate.

| Gate | Check | Value at 2026-09-10 snapshot | Tolerance |
| --- | --- | --- | --- |
| Ladder sum | Raw sum of each ladder before renormalizing | 101¢ to 107¢ | \[0.95, 1.15\] |
| Senate stitch, upper | Base P(>52) against extension P(≥53) | 22¢ against 22¢ | ≤ 2pt |
| Senate stitch, lower | Base cumulative P(≤52) against extension P(<53) | 84¢ against 79¢ — known break | ≤ 3pt |
| House parity | R P(≥218) against D P(≤217) | 19¢ against 18¢ | ≤ 3pt |
| Control marginal | Combo-implied D-Senate against ladder P(D≥51) | 49¢ against 51¢ | ≤ 4pt |
| Quote staleness | Trade age per bucket; count of buckets with no two-sided quote | — | Config |

On House parity: R holding 218 or more and D holding 217 or fewer are the same event, so the two probabilities should be equal, not sum to 1.

The lower Senate stitch gate failed at the snapshot and is expected to fail on thin low buckets pricing at 2–3¢. Treat a persistent break as an ingestion problem to investigate, not as noise to average over.

## Blocking unknowns

Resolve these against the API before writing the fitting code. Every price in this doc is scrape-derived.

1. **Strike width and full strike list for both approval series.** Only one sample strike is known (39.0%). Check the realized daily change distribution of the RCP average against the width — if brackets are wider than a typical one-day move, most mass sits in one bucket, the daily fit is ill-conditioned, and the weekly tenor becomes the anchor instead.
2. **Actual cadence of `KXTRUMPAPPROVE`.** Daily is assumed from per-day event tickers including a Sunday. Confirm weekend and holiday behaviour.
3. **Whether both approval ladders carry open-ended tails on both sides.**
4. **`KXBALANCEPOWERCOMBO` settlement rule.** The `27FEB` suffix implies a February 2027 expiry, which is neither Election Day nor the 2027-01-03 seating.
5. **Whether historical candlesticks or trades are available for these series, and at what granularity.** This decides whether the midterm sleeve has any pre-launch baseline at all, which drives the `min_history` behaviour above.
6. **One cross-check disagreed.** The seat ladder (51¢), the combo (49¢) and Polymarket (53¢) put D-Senate control in a tight band, while Kalshi's category page payout multiple implied roughly 42¢. Confirm that page is serving a display artifact — it also returned past-dated strikes — before trusting anything scraped from it.

## Acceptance tests

- [ ] Threshold ladder differencing yields a monotone density; a non-monotone result rejects the snapshot.
- [ ] A barrier series is excluded by the classifier, and an unknown `strike_type` raises rather than defaulting to the partitioned path.
- [ ] On a synthetic ladder drawn from a known normal, recovered σ is within tolerance; widening the open-ended tail bucket moves σ in the expected direction.
- [ ] The five parity gates re-run on live data and reproduce the snapshot relationships within tolerance.
- [ ] A deliberately corrupted ladder trips its gate and the snapshot is excluded from the index.
- [ ] With synthetic unit-normal sleeves, dropping from k=3 to k=1 leaves Z's variance unchanged. This is the test mean(z) fails.
- [ ] Re-running an identical snapshot inserts no rows and changes no published value.
- [ ] The last pre-election snapshot produces a finite normalized σ with `T_min` applied.
