"""Backtest (docs/specs/P1.md, Validation table): walk-forward skill via P5's forecast code.

12 weekly folds for slowdowns and 6 for dark_small with a 7-day embargo; core.split.folds and
config split.n_folds_* fix both, and forecast_all runs them. A forced baseline keeps it from
writing to DECISIONS.md: validation reports skill, it never chooses the model.
"""

import pandas as pd

from core import io
from core.config import load

COLUMNS = ["event_type", "model", "mean", "min", "max"]


def backtest(event_type: str, *, n_folds: int | None = None) -> pd.DataFrame:
    """n_folds overrides this event type's split.n_folds_* (validate.quick, #343)."""
    try:
        from forecast import forecast_all
    except ImportError:  # P5's forecast not on integration yet
        return pd.DataFrame(columns=COLUMNS)
    cfg, _ = load(io.CONFIG_PATH)
    if n_folds is not None:
        key = "n_folds_slowdown" if event_type == "slowdown" else "n_folds_small"
        cfg = {**cfg, "split": {**cfg["split"], key: n_folds}}
    cells = pd.DataFrame(io.read_stage("reference/cells").drop(columns="geometry"))
    T = pd.Timestamp(io.read_snapshot()["T"])
    keep = {
        "slowdown": "ewma",
        "dark_small": "ewma",
    }  # any fixed choice: skill is the same for every model
    _, report = forecast_all(
        io.read_stage("aggregate/observed"), cells, T, cfg, "", "", baseline=keep
    )
    r = report[report["event_type"] == event_type]
    return r.rename(columns={"skill_mean": "mean", "skill_min": "min", "skill_max": "max"})[
        COLUMNS
    ].reset_index(drop=True)
