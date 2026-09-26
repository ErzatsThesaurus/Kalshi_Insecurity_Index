# KIIX political sleeves

Ingestion for the three political sleeves — approval, midterm, control — that fold
into the existing KIIX composite index. Design and rationale live in
[KIIX Politics Sleeves — Implementation Spec.md](KIIX%20Politics%20Sleeves%20—%20Implementation%20Spec.md);
this file covers how to run it.

The weather sleeve is not touched by anything here.

## Run

```bash
python ingest/snapshot.py --sleeve approval --summary
python ingest/snapshot.py --sleeve midterm --strict
python ingest/snapshot.py --sleeve control --orderbook
```

Snapshots land in `data/<sleeve>/YYYY/MM/DD/snapshot_<captured_at>.json`, with
`data/<sleeve>/latest.json` pointing at the most recent. `captured_at` is fixed
once per run and is the snapshot's identity, so re-running the same
`--captured-at` writes nothing.

Exit codes: `0` written or nothing to do, `1` ingest failed, `2` a critical alert
fired under `--strict`.

Deployment is `deploy/systemd/` — see its README. Reads are public; no API
credentials anywhere in this package.

## Layout

| Module | Responsibility |
| --- | --- |
| `kiix/registry.py` | the seven series: sleeve, role, tenor, horizon, stitch group, event filter |
| `kiix/kalshi.py` | HTTP client, cursor pagination, category discovery |
| `kiix/convert.py` | decimal-dollar strings to integer cents |
| `kiix/schema.py` | market normalization, strike derivation, structure classification |
| `kiix/diagnostics.py` | per-event quote and geometry diagnostics |
| `kiix/snapshot.py` | assembly, sharded paths, idempotent writes, retirement |
| `kiix/cli.py` | shared flags, exit semantics, summary printer |
| `ingest/snapshot.py` | the single entry point, so one systemd template serves every sleeve |

Adding a sleeve means adding rows to `kiix/registry.py`, not a new script.

## What the live API actually does

Verified 2026-09-26, and several points contradict the spec:

- **Categories disagree.** The approval series report `Politics`; the seat and
  chamber-control series are only reachable under `Elections`. Discovery unions
  both. The spec's `GET /series?category=Politics` alone would return nothing for
  two of the three sleeves.
- **Four strike encodings coexist.** Approval uses `between`/`less`/`greater` with
  numeric strikes. The Senate ladders use `custom` with numeric strikes and tails
  as bounded domain intervals (`Below 45` = `[0, 44]`). The House ladders use
  `custom` with **no numeric strikes at all** — the range exists only as a string
  under `custom_strike`. The combo market is genuinely categorical. Structure is
  therefore classified from geometry; `strike_type` is only used to catch barriers.
- **`custom_strike` is inconsistent within one ladder.** `KXDHOUSESEATS` gives the
  range on interior buckets but a bare reference point on the tails. Parses are
  scored and the more informative one wins. Every market records `strike_source`,
  and a ladder relying on parsed strings raises a warning.
- **`KXDSENATESEATS` carries two live events**, `-27` and `-29`. The registry's
  `event_suffix` keeps the 2028 cycle out of the midterm fit.
- **Approval cadence is 7 days a week**, weekends included, settling 13:00 ET;
  `KXAPRPOTUS` settles 11:00 ET Friday.
- **Candlesticks are available** with OHLC on bid and ask as well as price, so
  pre-launch baselines for `min_history` are obtainable.
- Bucket widths: approval 0.1pp point masses (daily) and 0.3pp intervals
  (weekly); Senate 1 seat, R House 5 seats, D House 4 seats.

## Known gaps

- **No backup for `data/`.** It is gitignored and irreplaceable. This needs an
  answer before the timers run for long.
- **No tests.** `kiix/schema.py` carries the parsing and classification logic
  whose failure mode is silent misclassification.
- **Quote staleness has no trade age.** `updated_time` is book activity, not trade
  time; the spec's staleness gate needs the `/trades` endpoint.
- **Cumulative ladders are detected but not fitted.** Differencing is not
  implemented; such a ladder is excluded and warned on.
- **`--captured-at` is not validated**, so a malformed value is written into the
  data as-is.
