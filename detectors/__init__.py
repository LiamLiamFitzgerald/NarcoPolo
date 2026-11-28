"""P6 detectors: per-cell surprise scores -> fuse/cells.parquet."""

from detectors.scores import (
    bh,
    context_slowdown,
    context_small,
    cusum,
    fuse,
    gi_star,
    pearson_z,
    run_cells,
    score_cells,
    tail_pmid,
)

run = run_cells  # make all entry point (DECISIONS.md, 2026-11-27 18:30)

__all__ = [
    "bh", "context_slowdown", "context_small", "cusum", "fuse", "gi_star", "pearson_z", "run", "run_cells",
    "score_cells", "tail_pmid",
]  # fmt: skip
