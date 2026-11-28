#!/usr/bin/env python3
"""make demo (#343): `make all` (which ends with export) on top of an existing reports/validation.json.
Never runs validate; a missing report is said once and the dashboard shows "validation not run".
Windows (no make): `uv run python -m scripts.demo`."""

import os
from collections.abc import Callable
from pathlib import Path

from core import io
from scripts import run_all

MISSING = (
    "validation report missing: run `make validate` or `make validate-quick` first; "
    "the proof panel will show 'validation not run'"
)


def main(run: Callable[[], None] = run_all.main) -> None:
    # the same path export reads
    report = Path(os.environ.get("NARCO_REPORTS", io.ROOT / "reports")) / "validation.json"
    print(f"== reusing {report}" if report.exists() else MISSING, flush=True)
    run()


if __name__ == "__main__":
    main()
