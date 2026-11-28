"""Null test (docs/specs/P1.md, Validation table): circularly shift each cell's event times, rerun fuse.run.

Each (cell_id, event_type) series gets its own random offset in days, wrapping inside the observed date range
(Lotwick and Silverman: each series keeps its own structure, the timing between series is broken). Its observed and
expected rows move with its events, so counts never land on a day with no exposure.
"""

import time
from typing import Any

import numpy as np
import pandas as pd

from core import io

_NAMES = (
    "aggregate/observed",
    "forecast/expected",
    "reference/cells",
    "reference/travel_hours",
    "match/events",
)
_BUDGET_S = 30.0  # A13: one fuse.run slower than this means fewer runs


def _shift(frames: dict[str, pd.DataFrame], rng: np.random.Generator) -> dict[str, pd.DataFrame]:
    obs, exp, ev = frames["aggregate/observed"], frames["forecast/expected"], frames["match/events"]
    start, n = min(obs["date"]), (max(obs["date"]) - min(obs["date"])).days + 1
    keys = (
        pd.concat([f[["cell_id", "event_type"]] for f in (obs, exp, ev)])
        .drop_duplicates()
        .sort_values(["cell_id", "event_type"])
    )
    offset = pd.Series(rng.integers(0, n, len(keys)), index=pd.MultiIndex.from_frame(keys))

    def days(f: pd.DataFrame) -> np.ndarray:
        return offset.reindex(pd.MultiIndex.from_arrays([f["cell_id"], f["event_type"]])).to_numpy(
            int
        )

    def by_date(f: pd.DataFrame) -> pd.DataFrame:
        d0 = np.datetime64(start, "D")
        d = (pd.to_datetime(f["date"]).to_numpy().astype("datetime64[D]") - d0).astype(int) + days(
            f
        )
        return f.assign(date=pd.to_datetime(d0 + d % n))  # same type core.io.read_stage gives

    t0 = pd.Timestamp(start, tz="UTC")
    d = ((ev["time_utc"] - t0).dt.total_seconds() // 86400).to_numpy(int)
    moved = ev["time_utc"] + pd.to_timedelta((d + days(ev)) % n - d, unit="D")
    return {
        **frames,
        "aggregate/observed": by_date(obs),
        "forecast/expected": by_date(exp),
        "match/events": ev.assign(time_utc=moved),
    }


def _fuse(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """fuse.run on (shifted) frames, with the cell scores recomputed from the same frames (#177): fuse may not import
    detectors, so without them no slowdown gets a link score and the null test would test nothing."""
    from fuse import run  # validate may import fuse and detectors (tach.toml)

    try:
        from detectors import score_cells
    except ImportError:  # detectors without a pure scorer: fuse runs without cell scores
        return run(*(frames[k] for k in _NAMES))
    T = io.read_snapshot()["T"]
    cells = score_cells(
        frames["aggregate/observed"],
        frames["forecast/expected"],
        frames["reference/cells"],
        frames["match/events"],
        T,
    )
    return run(*(frames[k] for k in _NAMES), cells=cells, T=T)


def _flagged(frames: dict[str, pd.DataFrame]) -> bool:
    return bool(_fuse(frames)[1]["bh_flag"].any())


def null_test(runs: int = 200, seed: int = 0) -> dict[str, Any]:
    """Share of shifted runs with at least one flagged site; near or below q if fuse controls false discoveries.
    Returns runs 0 and share None while fuse.run is missing or a stub (it scores no cells). Whether fuse flags
    anything on the unshifted data does not matter: the null runs are counted either way."""
    from validate.checks import wilson  # checks imports this module

    frames = {k: io.read_stage(k) for k in _NAMES}
    try:
        if _fuse(frames)[
            0
        ].empty:  # P6's stub returns no cells; real fuse scores every observed row
            return {"runs": 0, "share_with_any_flag": None}
    except ImportError:
        return {"runs": 0, "share_with_any_flag": None}
    rng = np.random.default_rng(seed)
    tic = time.perf_counter()
    hits = [_flagged(_shift(frames, rng))]
    one = time.perf_counter() - tic
    if one > _BUDGET_S:  # keep the total near what `runs` calls at the budget would take
        runs = max(1, int(runs * _BUDGET_S / one))
    hits += [_flagged(_shift(frames, rng)) for _ in range(runs - 1)]
    k = sum(hits)
    lo, hi = wilson(k, len(hits))
    return {"runs": len(hits), "share_with_any_flag": k / len(hits), "lo": lo, "hi": hi}
