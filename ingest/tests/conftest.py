"""Shared fixtures: one simulated raw/ per session, and fakes that serve it in each provider's format."""

import zipfile
from datetime import date
from pathlib import Path

import netCDF4
import numpy as np
import pytest

import sim.simulate
from core import io
from core.config import load

SEED = 20261127
CFG = load(io.CONFIG_PATH)[0]


@pytest.fixture(scope="session")
def simraw(tmp_path_factory):
    root = tmp_path_factory.mktemp("sim")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("NARCO_DATA", str(root / "data"))
        mp.setenv("NARCO_RAW", str(root / "raw"))
        sim.simulate.simulate(CFG, SEED)
    return root / "raw"


class FakeCDS:
    """cdsapi.Client stand-in: answers each request with the simulator's ERA5 hours, in CDS's netCDF4 layout
    (valid_time in seconds since 1970). split=True zips wind and waves as two files, as CDS may do.
    The first swh value is stored as a missing value (a land point) to check it comes back NaN, never 0."""

    def __init__(self, sim_nc: Path, split: bool = False):
        self.sim_nc, self.split, self.calls = sim_nc, split, []

    def retrieve(self, dataset: str, request: dict, target: str) -> None:
        self.calls.append((dataset, request))
        with netCDF4.Dataset(self.sim_nc) as s:
            when = np.asarray(netCDF4.num2date(s["time"][:], s["time"].units))
            days = {
                date(int(request["year"][0]), int(request["month"][0]), int(d))
                for d in request["day"]
            }
            keep = np.array([date(w.year, w.month, w.day) in days for w in when])
            sel = {n: np.asarray(s[n][:])[keep] for n in ("u10", "v10", "swh")}
            secs = netCDF4.date2num(when[keep], "seconds since 1970-01-01").astype("int64")
            lat, lon = np.asarray(s["latitude"][:]), np.asarray(s["longitude"][:])
        groups = [("u10", "v10"), ("swh",)] if self.split else [("u10", "v10", "swh")]
        files = [Path(f"{target}.{i}.nc") for i in range(len(groups))]
        for f, names in zip(files, groups, strict=True):
            with netCDF4.Dataset(f, "w") as nc:
                for name, data, units, dtype in (
                    ("valid_time", secs, "seconds since 1970-01-01", "i8"),
                    ("latitude", lat, "degrees_north", "f8"),
                    ("longitude", lon, "degrees_east", "f8"),
                ):
                    nc.createDimension(name, len(data))
                    v = nc.createVariable(name, dtype, (name,))
                    v.units, v[:] = units, data
                for n in names:
                    v = nc.createVariable(
                        n, "f4", ("valid_time", "latitude", "longitude"), fill_value=-9999.0
                    )
                    v.units = "m" if n == "swh" else "m s**-1"
                    data = np.ma.masked_invalid(sel[n])
                    if n == "swh":
                        data[0, 0, 0] = np.ma.masked
                    v[:] = data
        if self.split:
            with zipfile.ZipFile(target, "w") as z:
                for f, stream in zip(files, ("oper", "wave"), strict=True):
                    z.write(f, f"data_stream-{stream}.nc")
        else:
            files[0].rename(target)
