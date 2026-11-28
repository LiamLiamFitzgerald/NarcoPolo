"""ERA5 hourly single levels from the Climate Data Store (cdsapi): 10 m wind u, v and significant wave height.

cdsapi reads the key itself from ~/.cdsapirc or CDSAPI_URL / CDSAPI_KEY; this module never touches it.
One CDS request per calendar month (exact days only), merged into raw/era5.nc in the simulator's layout:
u10, v10, swh on (time, latitude, longitude), time in hours since 1900-01-01 UTC. Values are untouched.
"""

import tempfile
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np

from core.io import raw_root
from ingest.cache import cached, record

# TODO(P2): move to config.yaml `ingest:` (question issue #216); CDS catalogue id of "ERA5 hourly data on single levels"
_DATASET = "reanalysis-era5-single-levels"
_VARIABLES = (
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "significant_height_of_combined_wind_waves_and_swell",
)
_SHORT = ("u10", "v10", "swh")  # the netCDF names CDS gives those three
_EPOCH = "hours since 1900-01-01 00:00:00.0"
# TODO(P2): confirm the exact licence name on the CDS dataset page (question issue #216)
_LICENCE = (
    "Copernicus Climate Change Service (C3S) Climate Data Store, ERA5 hourly data on single levels; "
    "terms as accepted on the CDS dataset page. Attribution: Generated using Copernicus Climate Change "
    "Service information; neither the European Commission nor ECMWF is responsible for any use."
)

Bbox = tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max (WGS84)


def _client() -> Any:
    import cdsapi  # pyright: ignore[reportMissingImports]  # not in pyproject yet (issue #215)

    return cdsapi.Client(quiet=True, progress=False)


def _cds_requests(bbox: Bbox, start: date, end: date) -> list[dict]:
    """One request per calendar month listing only the window's days, so nothing outside it is fetched."""
    lon_min, lat_min, lon_max, lat_max = (float(v) for v in bbox)
    months: dict[tuple[int, int], list[date]] = {}
    for i in range((end - start).days + 1):
        d = start + timedelta(days=i)
        months.setdefault((d.year, d.month), []).append(d)
    return [
        {
            "product_type": ["reanalysis"],
            "variable": list(_VARIABLES),
            "year": [f"{y}"],
            "month": [f"{m:02d}"],
            "day": [f"{d.day:02d}" for d in days],
            "time": [f"{h:02d}:00" for h in range(24)],  # UTC
            "area": [lat_max, lon_min, lat_min, lon_max],  # N, W, S, E
            "grid": [
                0.25,
                0.25,
            ],  # #216 (Liam, 28 Nov): CDS interpolates waves (native 0.5°) to the data dictionary's 0.25°
            "data_format": "netcdf",
            "download_format": "unarchived",
        }
        for (y, m), days in months.items()
    ]


def _netcdfs(download: Path) -> list[Path]:
    """CDS may zip one file per stream (wind and waves); unpack if so."""
    if not zipfile.is_zipfile(download):
        return [download]
    out = download.with_suffix(".d")
    with zipfile.ZipFile(download) as z:
        names = [n for n in z.namelist() if n.endswith(".nc")]
        z.extractall(out, members=names)
    return [out / n for n in names]


def _read(path: Path) -> dict[str, Any]:
    with netCDF4.Dataset(path) as nc:
        tname = "valid_time" if "valid_time" in nc.variables else "time"
        t = nc.variables[tname]
        when = netCDF4.num2date(t[:], t.units, getattr(t, "calendar", "standard"))
        part = {
            "time": np.asarray(netCDF4.date2num(when, _EPOCH), dtype=np.int64),
            "latitude": np.asarray(nc.variables["latitude"][:], dtype=np.float32),
            "longitude": np.asarray(nc.variables["longitude"][:], dtype=np.float32),
            "vars": {},
        }
        for name in _SHORT:
            if name in nc.variables:
                v = nc.variables[name]
                data = np.ma.filled(np.ma.asarray(v[:], dtype=np.float32), np.nan)  # missing -> NaN
                part["vars"][name] = (data, v.units)
    return part


def _write(path: Path, parts: list[dict[str, Any]]) -> None:
    lat, lon = parts[0]["latitude"], parts[0]["longitude"]
    chunks: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {n: [] for n in _SHORT}
    units: dict[str, str] = {}
    for p in parts:
        if not (np.array_equal(p["latitude"], lat) and np.array_equal(p["longitude"], lon)):
            raise ValueError("ERA5 parts come on different grids; not regridding in ingest")
        for name, (data, unit) in p["vars"].items():
            chunks[name].append((p["time"], data))
            units[name] = unit
    if missing := [n for n in _SHORT if not chunks[n]]:
        raise ValueError(f"CDS returned no {missing}")
    time, merged = None, {}
    for name in _SHORT:
        t = np.concatenate([c[0] for c in chunks[name]])
        order = np.argsort(t, kind="stable")
        if time is None:
            time = t[order]
        elif not np.array_equal(time, t[order]):
            raise ValueError(f"{name} has a different time axis from {_SHORT[0]}")
        merged[name] = np.concatenate([c[1] for c in chunks[name]])[order]
    assert time is not None
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as nc:
        nc.title = f"ERA5 hourly single levels ({_DATASET}), Copernicus Climate Data Store"
        for name, data, unit, dtype in (
            ("time", time, _EPOCH, np.int32),
            ("latitude", lat, "degrees_north", np.float32),
            ("longitude", lon, "degrees_east", np.float32),
        ):
            nc.createDimension(name, len(data))
            var = nc.createVariable(name, dtype, (name,))
            var.units = unit
            var[:] = data.astype(dtype)
        for name in _SHORT:
            var = nc.createVariable(
                name, np.float32, ("time", "latitude", "longitude"), fill_value=np.float32(np.nan)
            )
            var.units = units[name]
            var[:] = merged[name]


def fetch_era5(bbox: Bbox, start: date, end: date) -> Path:
    """raw/era5.nc for [start, end] (UTC days, end included) over bbox; a cached request downloads nothing."""
    requests = _cds_requests(bbox, start, end)
    req = {"source": "era5", "dataset": _DATASET, "requests": requests}
    if (hit := cached(req)) is not None:
        return hit
    path = raw_root() / "era5.nc"
    path.parent.mkdir(parents=True, exist_ok=True)
    client = _client()
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        parts = []
        for i, cds_request in enumerate(requests):
            target = Path(tmp) / f"part{i}.download"
            client.retrieve(_DATASET, cds_request, str(target))
            parts += [_read(p) for p in _netcdfs(target)]
        _write(path, parts)
    record(req, path, _LICENCE)
    return path
