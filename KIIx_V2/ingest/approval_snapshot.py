#!/usr/bin/env python3
"""Deprecated shim: forwards to ingest/snapshot.py --sleeve approval.

Kept only so the currently written systemd unit's ExecStart keeps working. Once
the units are converted to the kiix-snapshot@.service template, delete this file
and call ingest/snapshot.py directly.

Everything this script used to contain now lives in the kiix package:
    Client, discovery          -> kiix/kalshi.py
    cents, as_float            -> kiix/convert.py
    normalize_market           -> kiix/schema.py
    ladder_diagnostics         -> kiix/diagnostics.py
    build_snapshot, paths      -> kiix/snapshot.py
    flags, exit codes, summary -> kiix/cli.py
    SLEEVE_PATTERNS            -> kiix/registry.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kiix.cli import print_summary, run  # noqa: E402

if __name__ == "__main__":
    print(
        "note: approval_snapshot.py is deprecated; use "
        "`ingest/snapshot.py --sleeve approval`",
        file=sys.stderr,
    )
    raise SystemExit(run(["--sleeve", "approval", *sys.argv[1:]], summary=print_summary))
