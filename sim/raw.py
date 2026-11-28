"""raw/ files other than s1 and the static layers: GFW SAR, GFW presence, ERA5 and the manifest. Reads the SimWorld only.
Also writes the stage file reference/presence_2km (#208) from the same presence draws, so it matches raw/.

Shaped like docs/shared.md "Raw inputs": positions in lon/lat (as the sources deliver them), times in UTC.
- gfw_sar.parquet: scene_id, timestamp, lon, lat, matched, length_m. matched = an AIS-carrying ship.
- gfw_presence.parquet: lon, lat (south-west corner of a 0.01 degree cell), date, speed_bin (knots), vessel_type, hours.
- era5.nc: u10, v10 (m/s), swh (m) on (time, latitude, longitude); 0.25 degree grid, latitude descending, swh NaN on land.
- manifest.json: per file request, sha256, download_time, licence; plus `latest` (A11).
"""

import hashlib
import json
from datetime import datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.io import netcdf_file

from core import io
from core.crs import to_utm, to_wgs84
from core.grid import FINE, _origin, cell_id, cell_index
from sim.world import SimWorld

# TODO(P1): not in the spec; move into config.yaml sim: once the raw issue settles
_SHIP_LENGTH_M = (50.0, 300.0)  # GFW SAR length estimate of an AIS-carrying ship
_GFW_LARGE_M = (
    12.0  # small boats this long or longer also show in GFW SAR (the sim's "large" size class)
)
_LANE_HOURS = 1.0  # mean transit presence-hours per lane cell-day
_PRESENCE_DEG = 0.01  # GFW presence grid
_ERA5_DEG = 0.25
_SLOW, _FAST = "0-2", "8+"  # speed bins in knots: slowdowns, lane transit
_TYPES = np.array(["cargo", "tanker"])


def _ll(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lon, lat = to_wgs84(x, y)
    return np.round(lon, 6), np.round(lat, 6)


def _gfw_sar(world: SimWorld, rng: np.random.Generator) -> pd.DataFrame:
    """Ships inside a pass footprint on the pass day (the rule simulate uses for ghosts), plus long detected boats."""
    x0, _ = _origin()
    p, sh = world.passes, world.ships
    k = (
        sh["day"]
        .astype(int)
        .map({int(d): i for i, d in enumerate(p["day"])})
        .fillna(-1)
        .astype(int)
    )
    k = k.to_numpy()
    xc = (sh["x_m"].to_numpy() - x0) / FINE
    seen = (k >= 0) & (p["a"].to_numpy()[k] <= xc) & (xc <= p["b"].to_numpy()[k])
    ships = sh[seen].assign(
        k=k[seen], matched=True, length_m=rng.uniform(*_SHIP_LENGTH_M, seen.sum())
    )
    b = world.boats
    boats = b[b["detected"] & (b["length_m"] >= _GFW_LARGE_M)].assign(
        k=lambda d: d["pass"], matched=False
    )
    out = pd.concat([ships, boats], ignore_index=True)
    lon, lat = _ll(out["x_m"].to_numpy(), out["y_m"].to_numpy())
    return pd.DataFrame(
        {
            "scene_id": p["pass_id"].to_numpy()[out["k"].to_numpy()],
            "timestamp": p["time_utc"].to_numpy()[out["k"].to_numpy()],
            "lon": lon,
            "lat": lat,
            "matched": out["matched"].to_numpy(bool),
            "length_m": np.round(out["length_m"].to_numpy(float), 1),
        }
    ).sort_values(["timestamp", "lon", "lat"], ignore_index=True)


def _presence_rows(world: SimWorld, rng: np.random.Generator) -> pd.DataFrame:
    """Slowdown hours in the slow bin where each ship stopped; transit hours in the fast bin along the lane."""
    x0, y0 = _origin()
    sh = world.ships
    lane = world.fine[world.fine["lane"]]
    lane_day = np.repeat(np.arange(world.days), len(lane))
    lane_ix, lane_iy = (
        np.tile(lane["ix"].to_numpy(), world.days),
        np.tile(lane["iy"].to_numpy(), world.days),
    )
    rows = pd.DataFrame(
        {
            "x": np.concatenate([sh["x_m"].to_numpy(), x0 + (lane_ix + 0.5) * FINE]),
            "y": np.concatenate([sh["y_m"].to_numpy(), y0 + (lane_iy + 0.5) * FINE]),
            "day": np.concatenate([sh["day"].to_numpy(int), lane_day]),
            "speed_bin": [_SLOW] * len(sh) + [_FAST] * len(lane_day),
            "vessel_type": rng.choice(_TYPES, len(sh) + len(lane_day)),
            "hours": np.concatenate(
                [sh["duration_min"].to_numpy() / 60, rng.exponential(_LANE_HOURS, len(lane_day))]
            ),
        }
    )
    rows["date"] = [world.start + timedelta(days=int(d)) for d in rows["day"]]
    return rows


def _gfw_presence(rows: pd.DataFrame) -> pd.DataFrame:
    rows = rows.copy()
    lon, lat = to_wgs84(rows["x"].to_numpy(), rows["y"].to_numpy())
    rows["lon"] = np.round(np.floor(lon / _PRESENCE_DEG) * _PRESENCE_DEG, 2)
    rows["lat"] = np.round(np.floor(lat / _PRESENCE_DEG) * _PRESENCE_DEG, 2)
    keys = ["lon", "lat", "date", "speed_bin", "vessel_type"]
    out = rows.groupby(keys, as_index=False, sort=True)["hours"].sum()
    out["hours"] = out["hours"].round(3)
    return out[out["hours"] > 0].reset_index(drop=True)  # GFW returns only cells with presence


def _presence_2km(rows: pd.DataFrame) -> pd.DataFrame:
    """reference/presence_2km (#208): the same hours summed on the 2 km cell they fall in, i.e. the exact answer an
    area-weighted regrid of raw/gfw_presence approximates."""
    ix, iy = cell_index(rows["x"].to_numpy(), rows["y"].to_numpy(), FINE)
    rows = rows.assign(cell_id=[cell_id(i, j, FINE) for i, j in zip(ix, iy, strict=True)])
    keys = ["cell_id", "date", "vessel_type", "speed_bin"]
    return rows.groupby(keys, sort=True)["hours"].sum().reset_index()


def _era5(world: SimWorld, rng: np.random.Generator, path: Path) -> None:
    """Spatially uniform wind and waves, constant through each day at world.weather's value; one direction per day."""
    bb = world.config["region_bbox"]
    lon = (
        np.arange(np.floor(bb["lon_min"] / _ERA5_DEG), np.ceil(bb["lon_max"] / _ERA5_DEG) + 1)
        * _ERA5_DEG
    )
    lat = (
        np.arange(np.ceil(bb["lat_max"] / _ERA5_DEG), np.floor(bb["lat_min"] / _ERA5_DEG) - 1, -1)
        * _ERA5_DEG
    )
    w = world.weather
    theta = rng.uniform(0, 2 * np.pi, world.days)
    hour = lambda a: (
        np.repeat(np.asarray(a, float), 24)[:, None, None] * np.ones((1, len(lat), len(lon)))
    )
    u, v = hour(w["wind_ms"] * np.sin(theta)), hour(w["wind_ms"] * np.cos(theta))
    swh = hour(w["hs_m"])
    # land: north of the simulated shore line
    _, y0 = _origin()
    shore = world.fine[world.fine["iy"] == world.fine["iy"].max()]
    shore_y = y0 + (shore["iy"].iloc[0] + shore["sea_frac"].iloc[0]) * FINE
    glon, glat = np.meshgrid(lon, lat)
    _, gy = to_utm(glon, glat)
    swh[:, gy > shore_y] = np.nan
    t0 = (datetime.combine(world.start, time()) - datetime(1900, 1, 1)) // timedelta(hours=1)
    with netcdf_file(path, "w") as f:
        f.title = "simulated ERA5 single levels"
        for name, n in (("time", world.days * 24), ("latitude", len(lat)), ("longitude", len(lon))):
            f.createDimension(name, n)
        for name, data, units in (
            (
                "time",
                np.arange(t0, t0 + world.days * 24, dtype=np.int32),
                "hours since 1900-01-01 00:00:00.0",
            ),
            ("latitude", lat.astype(np.float32), "degrees_north"),
            ("longitude", lon.astype(np.float32), "degrees_east"),
        ):
            var = f.createVariable(name, data.dtype, (name,))
            var[:], var.units = data, units
        for name, data, units in (("u10", u, "m s**-1"), ("v10", v, "m s**-1"), ("swh", swh, "m")):
            var = f.createVariable(name, np.float32, ("time", "latitude", "longitude"))
            var[:], var.units, var._FillValue = data.astype(np.float32), units, np.float32(np.nan)


def write_raw(world: SimWorld) -> None:
    root = io.raw_root()
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(world.seed + world.config["sim"]["seed_offsets"]["raw"])
    _gfw_sar(world, rng).to_parquet(root / "gfw_sar.parquet", index=False)
    presence = _presence_rows(world, rng)
    _gfw_presence(presence).to_parquet(root / "gfw_presence.parquet", index=False)
    io.write_stage("reference/presence_2km", _presence_2km(presence), "simulated")
    _era5(world, rng, root / "era5.nc")

    end = world.start + timedelta(days=world.days)
    last = (
        end - timedelta(days=1)
    ).isoformat()  # same as the snapshot simulate writes: no feed lag
    files = {
        p.relative_to(root).as_posix(): {
            "request": {"simulated": True, "seed": world.seed},
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "download_time": f"{end.isoformat()}T00:00:00Z",
            "licence": "simulated data, no third-party licence",
        }
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "manifest.json"
    }
    manifest = {
        "latest": dict.fromkeys(("radar", "gfw_presence", "gfw_sar", "era5"), last),
        "files": files,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
