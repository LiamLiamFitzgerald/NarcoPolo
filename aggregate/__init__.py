"""P5 aggregate: soft counts per 2 km cell, UTC date and event type, each paired with its exposure.

Dates are tz-naive pandas Timestamps at midnight, meaning the UTC date.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import pyarrow.parquet as pq

from core.config import load
from core.grid import parent
from core.io import CONFIG_PATH, read_snapshot, read_stage, stage_path, write_stage
from core.observed import Observed

EVENT_TYPES = ("dark_small", "slowdown")
_KEYS = ["cell_id", "date", "event_type"]


def _utc_date(times: pd.Series) -> pd.Series:
    t = pd.to_datetime(times, utc=True)
    return t.dt.tz_localize(None).dt.normalize()


def soft_counts(events: pd.DataFrame) -> pd.DataFrame:
    """C = sum of p per cell, UTC date and event type (principle 3: weak evidence adds up)."""
    e = events.assign(date=_utc_date(events["time_utc"]))
    return e.groupby(_KEYS, as_index=False).agg(count=("p", "sum"))


def history_dates(T: pd.Timestamp, cfg: Mapping[str, Any]) -> dict[str, pd.DatetimeIndex]:
    """Each type's own history up to T: ship data for slowdowns, radar for dark_small."""
    days = {
        "slowdown": _cfg(cfg, "ship_history_days"),
        "dark_small": _cfg(cfg, "radar_history_days"),
    }
    return {t: pd.date_range(end=T.normalize(), periods=n) for t, n in days.items()}


def exposure_rows(
    exposure: pd.DataFrame,
    cells: pd.DataFrame,
    dates: Mapping[str, pd.DatetimeIndex],
    slowdown_last_date: pd.Timestamp,
) -> pd.DataFrame:
    """Exposure E for every 2 km cell, date and event type, zeros included.

    dark_small: sum of exposure_small over that day's passes (rough passes already carry 0).
    slowdown: the cell's sea_frac per day, and 0 after GFW presence's latest date (A11).
    """
    fine = cells.loc[cells["level"] == 2000, ["cell_id", "sea_frac"]]

    small = fine[["cell_id"]].merge(pd.DataFrame({"date": dates["dark_small"]}), how="cross")
    passes = exposure.assign(date=_utc_date(exposure["time_utc"]))
    per_day = passes.groupby(["cell_id", "date"], as_index=False)["exposure_small"].sum()
    small = small.merge(per_day, on=["cell_id", "date"], how="left")
    small = small.assign(event_type="dark_small", exposure=small["exposure_small"].fillna(0.0))

    slow = fine.merge(pd.DataFrame({"date": dates["slowdown"]}), how="cross")
    slow = slow.assign(
        event_type="slowdown",
        exposure=slow["sea_frac"].where(slow["date"] <= slowdown_last_date, 0.0),
    )
    cols = [*_KEYS, "exposure"]
    return pd.concat([small[cols], slow[cols]], ignore_index=True)


def build_observed(counts: pd.DataFrame, exposure: pd.DataFrame) -> Observed:
    """Full grid at 2 km: every (cell, date, type) row, E = 0 rows kept with C = 0.

    Events outside a type's history window are dropped; one inside it where E = 0 raises.
    """
    frame = exposure.merge(counts, on=_KEYS, how="left")
    frame["count"] = frame["count"].fillna(0.0)
    frame["level"] = 2000
    return Observed(frame)


def to_coarse(observed: Observed) -> Observed:
    """10 km cells: sum C and E over the 25 children."""
    f = observed.frame.assign(cell_id=observed.frame["cell_id"].map(parent))
    coarse = f.groupby(_KEYS, as_index=False)[["count", "exposure"]].sum()
    return Observed(coarse.assign(level=10000))


def build(
    events: pd.DataFrame,
    exposure: pd.DataFrame,
    cells: pd.DataFrame,
    dates: Mapping[str, pd.DatetimeIndex],
    slowdown_last_date: pd.Timestamp,
) -> Observed:
    """The whole aggregate computation: 2 km rows plus their 10 km roll-up, both event types."""
    fine = build_observed(
        soft_counts(events), exposure_rows(exposure, cells, dates, slowdown_last_date)
    )
    return Observed(pd.concat([fine.frame, to_coarse(fine).frame], ignore_index=True))


def read_cells() -> pd.DataFrame:
    """Attributes of the cells layer of reference/layers.gpkg, validated by core.io; P5 needs no geometry."""
    return pd.DataFrame(read_stage("reference/cells").drop(columns="geometry"))


def stage(
    T: pd.Timestamp,
    slowdown_last_date: pd.Timestamp,
    cfg: Mapping[str, Any],
    provenance: Literal["simulated", "real"],
) -> Path:
    """make all: read P4's events, P3's exposure and cells; write aggregate/observed.parquet."""
    observed = build(
        read_stage("match/events"),
        read_stage("coverage/exposure"),
        read_cells(),
        history_dates(T, cfg),
        slowdown_last_date,
    )
    return write_stage("aggregate/observed", observed.frame, provenance)


def _provenance(name: str) -> Literal["simulated", "real"]:
    """Inherit 'simulated' or 'real' from an input stage file's core.io stamp.

    shortcut: reads core.io's parquet metadata key directly; swap for a core.io helper if P1 adds one.
    """
    meta = pq.read_schema(stage_path(name)).metadata or {}
    return json.loads(meta[b"narco"])["provenance"]


def _cfg(cfg: Mapping[str, Any], key: str) -> Any:
    if key not in cfg:
        raise KeyError(f"config.yaml has no {key!r}; P5's keys are listed in issue #69")
    return cfg[key]


def run() -> None:
    """make all entry point: T and GFW presence's latest date come from data/snapshot.json (A11)."""
    cfg, _ = load(CONFIG_PATH)
    snap = read_snapshot()
    stage(
        pd.Timestamp(snap["T"]),
        pd.Timestamp(snap["gfw_presence"]),
        cfg,
        _provenance("match/events"),
    )
