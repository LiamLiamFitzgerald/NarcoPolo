"""Which cells each radar pass saw, how well, and whether the sea was calm (docs/specs/P3.md).

ERA5 is passed around as a mapping (see _read_era5): time (datetime64, UTC), lat, lon (1-D, degrees), and u10, v10,
swh as (time, lat, lon) arrays with NaN waves over land. era5=None means weather unknown, which is never calm.
Thresholds are keyword arguments or config lookups with the spec's defaults until P3's config keys land (#85)."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.io import netcdf_file
from shapely.geometry.base import BaseGeometry

from core import io
from core.config import load
from core.crs import to_utm, to_wgs84
from core.schemas import SCHEMAS


def _cfg() -> Mapping[str, Any]:
    return load(Path(__file__).resolve().parent.parent / "config.yaml")[0]


def covered_frac(
    footprint: BaseGeometry, cells: gpd.GeoDataFrame, sea: BaseGeometry | None = None
) -> pd.Series:
    """area(footprint & cell & sea) / full cell area, so a half-land cell reaches at most 0.5. Without a sea geometry
    the cell's sea_frac stands in for it (exact when the sea spreads evenly across the part the footprint covers)."""
    full = cells.area
    if sea is not None:
        part = cells.intersection(footprint.intersection(sea)).area
    else:
        part = cells.intersection(footprint).area
        if "sea_frac" in cells:
            part = part * cells["sea_frac"]
    return pd.Series(
        (part / full).clip(0, 1).to_numpy(float), index=cells.index, name="covered_frac"
    )


def _read_era5(path: Path) -> dict[str, np.ndarray]:
    """ERA5 single levels as written by the CDS (netCDF3 here; scipy reads it, netCDF4 would need another library)."""
    with netcdf_file(path, "r", mmap=False) as f:
        v = f.variables
        units = v["time"].units.decode() if isinstance(v["time"].units, bytes) else v["time"].units
        step, _, origin = units.partition(" since ")
        t0 = np.datetime64(pd.Timestamp(origin).tz_localize(None))
        mult = {"hours": "h", "seconds": "s", "days": "D"}[step.strip()]
        time = t0 + v["time"][:].astype("int64").astype(f"timedelta64[{mult}]")

        def arr(name: str) -> np.ndarray:
            a = np.array(v[name][:], dtype=float)
            fill = getattr(v[name], "_FillValue", None)
            return np.where(a == fill, np.nan, a) if fill is not None and np.isfinite(fill) else a

        return {
            "time": time.astype("datetime64[ns]"),
            "lat": np.array(v["latitude"][:], float),
            "lon": np.array(v["longitude"][:], float),
            "u10": arr("u10"),
            "v10": arr("v10"),
            "swh": arr("swh"),
        }


def _points(
    era5: Mapping[str, np.ndarray], cells: gpd.GeoDataFrame
) -> tuple[np.ndarray, np.ndarray]:
    """Nearest ERA5 grid row and column for each cell centre."""
    c = cells.centroid
    lon, lat = to_wgs84(c.x.to_numpy(), c.y.to_numpy())
    return (
        np.abs(np.asarray(lat)[:, None] - era5["lat"][None, :]).argmin(1),
        np.abs(np.asarray(lon)[:, None] - era5["lon"][None, :]).argmin(1),
    )


def _wave_points(
    era5: Mapping[str, np.ndarray], cells: gpd.GeoDataFrame
) -> tuple[np.ndarray, np.ndarray]:
    """Nearest ERA5 grid point with valid waves for each cell centre (A8: waves are NaN over land), in metres."""
    valid = np.isfinite(era5["swh"]).any(axis=0)
    gi, gj = np.nonzero(valid)
    if not len(gi):
        return _points(era5, cells)
    gx, gy = to_utm(era5["lon"][gj], era5["lat"][gi])
    c = cells.centroid
    d = np.hypot(c.x.to_numpy()[:, None] - gx[None, :], c.y.to_numpy()[:, None] - gy[None, :])
    k = d.argmin(1)
    return gi[k], gj[k]


def _hour(era5: Mapping[str, np.ndarray], time: pd.Timestamp) -> int:
    t = np.datetime64(pd.Timestamp(time).tz_convert("UTC").tz_localize(None), "ns")
    return int(np.abs(era5["time"] - t).argmin())


def weather_at(
    era5: Mapping[str, np.ndarray] | None, cells: gpd.GeoDataFrame, time: pd.Timestamp
) -> tuple[pd.Series, pd.Series]:
    """(wind_ms, hs_m) per cell: nearest hour; nearest grid point for wind, and for waves the nearest point with valid
    waves (A8). wind = sqrt(u10^2 + v10^2). Unknown weather (era5=None) is NaN, which calm() treats as rough."""
    if era5 is None:
        nan = pd.Series(np.nan, index=cells.index)
        return nan.rename("wind_ms"), nan.copy().rename("hs_m")
    h = _hour(era5, time)
    i, j = _points(era5, cells)
    wi, wj = _wave_points(era5, cells)
    wind = np.hypot(era5["u10"][h, i, j], era5["v10"][h, i, j])
    hs = era5["swh"][h, wi, wj]
    return pd.Series(wind, index=cells.index, name="wind_ms"), pd.Series(
        hs, index=cells.index, name="hs_m"
    )


def calm(wind_ms: pd.Series, hs_m: pd.Series) -> pd.Series:
    """Calm if wind and wave height are both under their thresholds; unknown weather is not calm.
    The thresholds are provisional until P1's recall curve exists (spec warning)."""
    c = _cfg().get("coverage", {})
    wind_max = c.get("calm_wind_ms", 6)  # TODO(P3): config key pending #85
    hs_max = c.get("calm_hs_m", 1.5)  # TODO(P3): config key pending #85
    return ((wind_ms < wind_max) & (hs_m < hs_max)).rename("calm")


def _post_storm(
    era5: Mapping[str, np.ndarray] | None,
    cells: gpd.GeoDataFrame,
    time: pd.Timestamp,
    storm_hs_m: float = 2.5,
    hours: int = 24,
    lookback_h: int = 72,
) -> pd.Series:
    """A9: at least `hours` hourly wave heights over storm_hs_m in the lookback_h hours before the pass."""
    if era5 is None:
        return pd.Series(False, index=cells.index, name="post_storm")
    h = _hour(era5, time)
    wi, wj = _wave_points(era5, cells)
    window = era5["swh"][max(h - lookback_h, 0) : h, wi, wj]  # (hours, cells)
    return pd.Series((window > storm_hs_m).sum(0) >= hours, index=cells.index, name="post_storm")


def build_exposure(passes: pd.DataFrame, cells: gpd.GeoDataFrame, era5: Any) -> pd.DataFrame:
    """One row per 2 km cell and pass. `passes`: pass_id, time_utc, footprint (UTM), downloaded.
    exposure_small = covered_frac x calm; a pass not downloaded gives 0 everywhere, even where calm. post_storm (A9) is
    written once the coverage/exposure schema has the column (#85)."""
    fine = cells[cells["level"] == 2000]
    with_storm = "post_storm" in SCHEMAS["coverage/exposure"].columns
    rows = []
    for pass_id, time_utc, footprint, downloaded in zip(
        passes["pass_id"],
        passes["time_utc"],
        passes["footprint"],
        passes["downloaded"],
        strict=True,
    ):
        time_utc = pd.Timestamp(time_utc)
        cov = covered_frac(footprint, fine)
        wind, hs = weather_at(era5, fine, time_utc)
        ok = calm(wind, hs)
        frame = pd.DataFrame(
            {
                "cell_id": fine["cell_id"].to_numpy(),
                "pass_id": pass_id,
                "time_utc": time_utc,
                "covered_frac": cov.to_numpy(),
                "wind_ms": wind.to_numpy(),
                "hs_m": hs.to_numpy(),
                "calm": ok.to_numpy(),
                "exposure_small": (cov * ok * bool(downloaded)).to_numpy(),
            }
        )
        if with_storm:
            frame["post_storm"] = _post_storm(era5, fine, time_utc).to_numpy()
        rows.append(frame)
    return pd.concat(rows, ignore_index=True)


def _read_passes(s1: Path) -> pd.DataFrame:
    """One row per raw/s1/<hash>.json: pass_id, time_utc, footprint in UTM, downloaded (a scene file exists)."""
    rows = []
    for meta_path in sorted(s1.glob("*.json")):
        m = json.loads(meta_path.read_text())
        fp = shapely.from_wkt(m["footprint"])
        if m.get("footprint_crs", "EPSG:4326") != "EPSG:32629":
            fp = shapely.transform(fp, lambda xy: np.column_stack(to_utm(xy[:, 0], xy[:, 1])))
        rows.append(
            {
                "pass_id": m.get("pass_id", m["scene_id"]),
                "time_utc": pd.Timestamp(m["start_time"]).tz_convert("UTC"),
                "footprint": fp,
                "downloaded": meta_path.with_suffix(".tif").exists(),
            }
        )
    return pd.DataFrame(rows, columns=["pass_id", "time_utc", "footprint", "downloaded"])


def run() -> None:
    """make all. On the simulator (no raw/), `make sim` already wrote coverage/exposure: check it and stop."""
    if not (io.stage_path("coverage/exposure").parent.parent / "raw").exists():
        io.read_stage("coverage/exposure")
        return
    raise NotImplementedError(
        "coverage on real data: needs reference/cells from real data first (#34)"
    )
