"""ERA5 hourly single levels from the Climate Data Store (cdsapi): 10 m wind u, v and significant wave height."""

from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
from scipy.io import netcdf_file

from ingest import _stub

_DEG = 0.25  # ERA5 grid (Data dictionary)


def fetch_era5(bbox: _stub.Bbox, start: date, end: date) -> Path:
    """raw/era5.nc: u10, v10, swh on (time, latitude descending, longitude). Stub: every value NaN."""
    lon_min, lat_min, lon_max, lat_max = bbox
    lon = np.arange(np.floor(lon_min / _DEG), np.ceil(lon_max / _DEG) + 1) * _DEG
    lat = np.arange(np.ceil(lat_max / _DEG), np.floor(lat_min / _DEG) - 1, -1) * _DEG
    t0 = (datetime.combine(start, time()) - datetime(1900, 1, 1)) // timedelta(hours=1)
    n = ((end - start).days + 1) * 24  # UTC hours, end day included

    def write(path: Path) -> None:
        with netcdf_file(path, "w") as f:
            f.title = "ERA5 single levels (stub, no data)"
            axes = (
                (
                    "time",
                    np.arange(t0, t0 + n, dtype=np.int32),
                    "hours since 1900-01-01 00:00:00.0",
                ),
                ("latitude", lat.astype(np.float32), "degrees_north"),
                ("longitude", lon.astype(np.float32), "degrees_east"),
            )
            for name, data, units in axes:
                f.createDimension(name, len(data))
                var = f.createVariable(name, data.dtype, (name,))
                var[:], var.units = data, units
            nan = np.full((n, len(lat), len(lon)), np.nan, dtype=np.float32)
            for name, units in (("u10", "m s**-1"), ("v10", "m s**-1"), ("swh", "m")):
                var = f.createVariable(name, np.float32, ("time", "latitude", "longitude"))
                var[:], var.units, var._FillValue = nan, units, np.float32(np.nan)

    return _stub.get(_stub.request("era5", bbox, start, end), "era5.nc", write)
