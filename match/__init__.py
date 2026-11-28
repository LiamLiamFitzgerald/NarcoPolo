"""P4 match: GFW/AIS matching, dark_small and slowdown events."""

import logging

import numpy as np
import pandas as pd

from core import io
from core.crs import to_utm
from core.grid import FINE, centroid
from match._common import cell_ids
from match.events import (
    dark_small_events,
    match,
    ship_key,
    slowdowns_from_presence,
    slowdowns_from_tracks,
    write_events,
)

__all__ = [
    "dark_small_events",
    "match",
    "run",
    "ship_key",
    "slowdowns_from_presence",
    "slowdowns_from_tracks",
    "write_events",
]

log = logging.getLogger(__name__)


def _matched(dets: pd.DataFrame, gfw_sar: pd.DataFrame) -> np.ndarray:
    """match() against raw/gfw_sar, or all False when GFW gives only gridded SAR (shared.md issue 1 fallback)."""
    if gfw_sar.empty or gfw_sar["scene_id"].isna().all():
        log.warning(
            "gfw_sar is gridded (no scene_id): matching skipped, every candidate unmatched (shared.md issue 1)"
        )
        return np.zeros(len(dets), bool)
    x, y = to_utm(gfw_sar["lon"].to_numpy(), gfw_sar["lat"].to_numpy())
    g = gfw_sar.assign(x_m=x, y_m=y, time_utc=pd.to_datetime(gfw_sar["timestamp"], utc=True))
    return match(dets, g)


def _cells() -> pd.DataFrame:
    """2 km cells with their centre (core.grid), as slowdowns_from_presence places events."""
    cells = io.read_cells()
    cells = cells[cells["level"] == FINE].reset_index(drop=True)
    xy = np.array([centroid(c) for c in cells["cell_id"]]).reshape(-1, 2)
    return cells.assign(x_m=xy[:, 0], y_m=xy[:, 1])


def run() -> None:
    """make all entry point (DECISIONS.md 2026-11-27 18:30).

    Simulator: `make sim` already wrote the events file; it is re-validated and kept (detect keeps the
    simulator's detections, so there is nothing new to match).
    Real data: dark_small from detect/detections and raw/gfw_sar; slowdowns from reference/presence_2km and
    coverage/weather_daily (#208).
    """
    if io.read_provenance("detect/detections") == "simulated":
        io.write_stage("match/events", io.read_stage("match/events"), "simulated")
        return
    dets = io.read_stage("detect/detections")
    dets["cell_id"] = cell_ids(
        dets["x_m"].to_numpy(), dets["y_m"].to_numpy()
    )  # not a detections column
    cells = _cells()
    known = dets["cell_id"].isin(cells["cell_id"])
    if not known.all():
        log.warning("%d detections outside reference/cells dropped", int((~known).sum()))
    dets["matched"] = _matched(dets, pd.read_parquet(io.raw_root() / "gfw_sar.parquet"))
    slow = slowdowns_from_presence(
        io.read_stage("reference/presence_2km"), cells, io.read_stage("coverage/weather_daily")
    )
    write_events(dark_small_events(dets[known]), slow, provenance="real")
