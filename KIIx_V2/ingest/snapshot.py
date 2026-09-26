#!/usr/bin/env python3
"""Snapshot one KIIX political sleeve's Kalshi ladders to JSON.

The single entry point for every sleeve, so one systemd template unit can serve
all of them:

    python ingest/snapshot.py --sleeve approval --summary
    python ingest/snapshot.py --sleeve midterm --strict
    python ingest/snapshot.py --sleeve control --orderbook

Which series belong to which sleeve lives in kiix/registry.py. Series are
discovered from the API by category on every run; the registry says what each
discovered series means, and an entry that matches nothing raises a rename alert.

Reads are public; no API credentials are used.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Importable however it is invoked: `python ingest/snapshot.py` from any cwd, or
# `python -m ingest.snapshot`. Keeps the systemd ExecStart free of a
# WorkingDirectory dependency.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kiix.cli import print_summary, run  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:], summary=print_summary))
