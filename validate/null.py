"""Null test (docs/specs/P1.md, Validation table): circularly shift each cell's event times, rerun fuse.run."""

from typing import Any


def null_test(runs: int = 200, seed: int = 0) -> dict[str, Any]:
    return {
        "runs": 0,
        "share_with_any_flag": None,
    }  # TODO(P1): fuse.run on circularly shifted events
