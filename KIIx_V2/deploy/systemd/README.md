# Approval sleeve snapshot timer

Captures the Kalshi approval ladders (`KXTRUMPAPPROVE`, `KXAPRPOTUS`) every 15
minutes. Two-sided quotes and book depth are not backfillable, so this should go
up before any fitting work.

## Placeholders to reconcile before installing

These are guesses that must match the existing weather sleeve's unit:

| Placeholder | In | Notes |
| --- | --- | --- |
| `User=kiix` / `Group=kiix` | `.service` | must own `/opt/kiix/data` |
| `/opt/kiix` | both | repo root; the script resolves output paths from its own location, not the cwd |
| `/opt/kiix/.venv/bin/python` | `.service` | needs `requests` only |
| `OnFailure=kiix-alert@%n.service` | `.service` | commented out; point at the real ntfy handler |
| `HC_PING_URL` | `/etc/kiix/approval.env` | optional; unset skips the ping cleanly |

## Install

```bash
sudo install -m0644 deploy/systemd/kiix-approval-snapshot.service /etc/systemd/system/
sudo install -m0644 deploy/systemd/kiix-approval-snapshot.timer   /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/kiix-approval-snapshot.{service,timer}
sudo systemctl daemon-reload
```

Optional Healthchecks wiring:

```bash
sudo install -d -m0750 -o kiix -g kiix /etc/kiix
printf 'HC_PING_URL=https://hc-ping.com/%s\n' "<uuid>" | sudo tee /etc/kiix/approval.env
sudo chown kiix:kiix /etc/kiix/approval.env && sudo chmod 0640 /etc/kiix/approval.env
```

## Verify before enabling the timer

Run the service once by hand and confirm a snapshot lands:

```bash
sudo systemctl start kiix-approval-snapshot.service
sudo systemctl status kiix-approval-snapshot.service --no-pager
sudo journalctl -u kiix-approval-snapshot.service -n 40 --no-pager
ls -l /opt/kiix/data/approval/ | tail -5
```

A good run prints `wrote data/approval/snapshot_<ts>.json (17 markets, 0 alerts)`
and exits 0. A rename or an unmapped `strike_type` exits 2 under `--strict`.

Then enable:

```bash
sudo systemctl enable --now kiix-approval-snapshot.timer
systemctl list-timers kiix-approval-snapshot.timer --no-pager
```

## Operating notes

- **Idempotency.** `captured_at` is generated per run, so every tick writes a new
  file by design. Re-running the *same* `--captured-at` writes nothing, which is
  what makes replay safe.
- **Failure handling.** No `Restart=`; the next tick is 15 minutes away and a
  missed snapshot cannot be recovered retroactively.
- **Health semantics.** `--strict` turns a critical alert into exit 2, and the
  script skips the Healthchecks ping on any critical alert. So a rename both
  fails the unit and starves the dead-man's switch.
- **Volume.** ~80KB per snapshot, 96/day, so ~7.7MB/day and ~340MB through
  2026-11-03. Add `--orderbook` and that grows substantially.

## Known issue: flat output directory

At 96 files/day this reaches roughly 4,200 files in a single flat
`data/approval/` by Election Day. Sharding by UTC date
(`data/approval/2026/09/26/snapshot_<ts>.json`) is a small change to
`main()` in `ingest/approval_snapshot.py`, but doing it *after* the timer starts
writing splits the dataset across two layouts. Decide before enabling.
