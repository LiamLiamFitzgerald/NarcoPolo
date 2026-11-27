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
        return f.assign(date=(d0 + d % n).astype(object))

    t0 = pd.Timestamp(start, tz="UTC")
    d = ((ev["time_utc"] - t0).dt.total_seconds() // 86400).to_numpy(int)
    moved = ev["time_utc"] + pd.to_timedelta((d + days(ev)) % n - d, unit="D")
    return {
        **frames,
        "aggregate/observed": by_date(obs),
        "forecast/expected": by_date(exp),
        "match/events": ev.assign(time_utc=moved),
    }


def _flagged(frames: dict[str, pd.DataFrame]) -> bool:
    # validate may import fuse (tach.toml); fuse/ may not be on this branch yet
    from fuse import run

    _, sites = run(*(frames[k] for k in _NAMES))
    return bool(sites["bh_flag"].any())


def null_test(runs: int = 200, seed: int = 0) -> dict[str, Any]:
    """Share of shifted runs with at least one flagged site; near or below q if fuse controls false discoveries.
    Returns runs 0 and share None while fuse.run is missing or flags nothing on the unshifted data (a stub)."""
    from validate.checks import wilson  # checks imports this module

    frames = {k: io.read_stage(k) for k in _NAMES}
    try:
        if not _flagged(frames):
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
