"""Which cells each radar pass saw, how well, and whether the sea was calm (docs/specs/P3.md).
Stubs (#22): weather is unknown, so no pass counts as calm; the real coverage comes in #37."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry.base import BaseGeometry

from core import io
from core.config import load


def _cfg() -> Mapping[str, Any]:
    return load(Path(__file__).resolve().parent.parent / "config.yaml")[0]


def covered_frac(footprint: BaseGeometry, cells: gpd.GeoDataFrame) -> pd.Series:
    """area(footprint & cell & sea) / full cell area."""
    # stub: ignores land, so exact only for all-sea cells; #37 intersects with sea too
    return pd.Series(cells.intersection(footprint).area / cells.area, index=cells.index)


def weather_at(
    era5: Any, cells: gpd.GeoDataFrame, time: pd.Timestamp
) -> tuple[pd.Series, pd.Series]:
    """(wind_ms, hs_m) per cell: nearest hour and grid point; hs from the nearest point with valid waves (A8)."""
    nan = pd.Series(np.nan, index=cells.index)
    return nan, nan.copy()  # stub: unknown weather, which calm() treats as rough


def calm(wind_ms: pd.Series, hs_m: pd.Series) -> pd.Series:
    """Calm if wind and wave height are both under their thresholds; unknown weather is not calm."""
    c = _cfg().get("coverage", {})
    wind_max = c.get("calm_wind_ms", 6)  # TODO(P3): config key pending #85
    hs_max = c.get("calm_hs_m", 1.5)  # TODO(P3): config key pending #85
    return (wind_ms < wind_max) & (hs_m < hs_max)


def post_storm(era5: Any, cells: gpd.GeoDataFrame, time: pd.Timestamp) -> pd.Series:
    """A9: at least storm_hours of hs > storm_hs_m in the storm_lookback_h hours before the pass; unknown hs is not stormy."""
    c = _cfg()["coverage"]
    hours = [
        weather_at(era5, cells, time - pd.Timedelta(hours=h))[1]
        for h in range(1, int(c["storm_lookback_h"]) + 1)
    ]
    stormy = pd.concat(hours, axis=1).gt(c["storm_hs_m"]).sum(axis=1)  # NaN > x is False
    return stormy >= c["storm_hours"]


def build_exposure(passes: pd.DataFrame, cells: gpd.GeoDataFrame, era5: Any) -> pd.DataFrame:
    """One row per cell and pass. `passes`: pass_id, time_utc, footprint, downloaded.
    Not downloaded -> exposure_small 0; post_storm per A9."""
    fine = cells[cells["level"] == 2000]
    rows = []
    for pass_id, time_utc, footprint, downloaded in zip(
        passes["pass_id"],
        passes["time_utc"],
        passes["footprint"],
        passes["downloaded"],
        strict=True,
    ):
        cov = covered_frac(footprint, fine)
        wind, hs = weather_at(era5, fine, time_utc)
        ok = calm(wind, hs)
        rows.append(
            pd.DataFrame(
                {
                    "cell_id": fine["cell_id"].to_numpy(),
                    "pass_id": pass_id,
                    "time_utc": time_utc,
                    "covered_frac": cov.to_numpy(),
                    "wind_ms": wind.to_numpy(),
                    "hs_m": hs.to_numpy(),
                    "calm": ok.to_numpy(),
                    "exposure_small": (cov * ok * bool(downloaded)).to_numpy(),
                    "post_storm": post_storm(era5, fine, time_utc).to_numpy(),
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def run() -> None:
    """make all. On the simulator (no raw/), `make sim` already wrote coverage/exposure: check it and stop."""
    if not (io.stage_path("coverage/exposure").parent.parent / "raw").exists():
        io.read_stage("coverage/exposure")
        return
    raise NotImplementedError("coverage on real data: #37")
