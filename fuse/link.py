"""Lag link, drop sites, significance, recurrence, piers and reasons. STUBS (issue 24): every function
returns a neutral, schema-valid placeholder; the real steps from docs/specs/P6.md come in later issues."""

import numpy as np
import pandas as pd

from core import io
from fuse._common import PARAMS, _provenance

_SITE_COLUMNS = {
    "site_id": str, "x_m": float, "y_m": float, "n_slowdowns": int, "S": float, "p_perm": float,
    "bh_flag": bool, "recurrence": int, "followup_unobserved": int, "agreement": int, "reasons": object,
    "top_piers": object,
}  # fmt: skip
_CELL_COLUMNS = {
    "cell_id": str, "date": object, "event_type": str, "p_mid": float, "bh_flag": bool, "gi_z": float,
    "cusum_s": float, "context": float, "U": float, "agreement": int,
}  # fmt: skip


def followup_exposure(s, exposure, nbrs, days=PARAMS["link_days"]) -> float:  # stub, issue 24
    return 0.0  # 0 = "could not look", so link_score gives None


def link_score(s, U_small, nbrs, tau=PARAMS["tau_days"]) -> float | None:  # stub, issue 24
    return None  # never 0 when the follow-up was unobserved


def sites(slowdowns: pd.DataFrame) -> pd.DataFrame:  # stub, issue 24: one site per 2 km cell (A2)
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in _SITE_COLUMNS.items()})


def suppress(ranked_sites: pd.DataFrame, radius_m=PARAMS["link_radius_m"]) -> pd.DataFrame:
    return ranked_sites  # stub, issue 24


def site_score(L, ages, half_life=PARAMS["half_life_days"]) -> float:  # stub, issue 24
    return 0.0


def link_table(U_small, exposure, nbrs, days=PARAMS["link_days"], tau=PARAMS["tau_days"]):
    return {}  # stub, issue 24: best decayed U and X per (cell, date) (A4)


def permutation(
    slowdowns, link_table, n=None, shift_days=PARAMS["shift_days"], seed=None
) -> np.ndarray:
    return np.ones(len(slowdowns))  # stub, issue 24: n = max(999, ceil(10 m / q)) (A3)


def recurrence(L_site, median_L) -> int:  # stub, issue 24
    return 0


def pier_scores(
    sites, travel_hours, tau_h=PARAMS["pier_tau_h"]
) -> tuple[pd.Series, dict[str, list[str]]]:
    return pd.Series(dtype=float), {}  # stub, issue 24


def reasons(site, inputs) -> list[str]:  # stub, issue 24: template, identity-free
    return ["not scored yet (placeholder)"]


def run(observed=None, expected=None, layers=None, travel=None, events=None):
    """Pure (cells, sites) from the input frames; validate.null_test calls it this way.
    With no arguments (make all, DECISIONS.md 2026-11-27 18:30) it reads the stage files and writes fuse/sites."""
    if observed is None:
        return run_sites()
    return _run(observed, expected, layers, travel, events)


def _run(observed, expected, layers, travel, events) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The pure path of run(): frames in, (cells, sites) out, no file I/O (the null test calls it 200 times)."""
    cells = pd.DataFrame(
        {c: pd.Series(dtype=t) for c, t in _CELL_COLUMNS.items()}
    )  # stub, issue 24
    slow = events[events["event_type"] == "slowdown"] if events is not None else pd.DataFrame()
    return cells, suppress(sites(slow))


def run_sites() -> None:
    """Stage files -> fuse/sites.parquet."""
    names = [
        "aggregate/observed",
        "forecast/expected",
        "reference/cells",
        "reference/travel_hours",
        "match/events",
    ]
    _, out = _run(*(io.read_stage(n) for n in names))
    io.write_stage("fuse/sites", out, _provenance("aggregate/observed"))  # type: ignore[arg-type]
