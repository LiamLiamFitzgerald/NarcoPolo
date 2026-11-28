"""Shared fixtures: one simulated raw/ per session; fakes for CDS (ERA5) and the GFW client."""

import zipfile
from datetime import date
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd
import pytest

import sim.simulate
from core import io
from core.config import load
from ingest import gfw

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

# Placeholders, not real GFW filter syntax (that is open in #212): the tests only check pass-through.
SETTINGS = {
    "chunk_days": 2,
    "filter_join": " & ",
    "sar_matched": {"true": "m=1", "false": "m=0"},
    "vessel_types": {"cargo": "vt=cargo", "tanker": "vt=tanker"},
    "speed_bins": {"0-2": "s<2", "2+": "s>=2"},
}
# identity fields the API can return; ingest must never keep them
IDENTITY = {"mmsi": "fake-id", "ship_name": "FAKE NAME", "imo": "fake-imo", "call_sign": "FAKE"}


class _Result:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def df(self, include=None):
        frame = pd.DataFrame(self.rows)
        return frame[[c for c in frame.columns if include is None or c in include]]


class FakeClient:
    def __init__(self, calls: list):
        self.calls = calls
        self.fourwings = self

    def create_sar_presence_report(self, **kw):
        self.calls.append(("sar", kw))
        if kw["filters"] == ["m=0"]:
            return _Result([])  # an empty answer is a valid answer
        return _Result(
            [{"date": "2026-11-01T05", "lat": 51.5, "lon": -9.0, "detections": 2, **IDENTITY}]
        )

    def create_ais_presence_report(self, **kw):
        self.calls.append(("presence", kw))
        return _Result([{"date": "2026-11-01", "lat": 51.6, "lon": -8.5, "hours": 1.5, **IDENTITY}])


@pytest.fixture
def fake_gfw(monkeypatch):
    """The list of (dataset, kwargs) calls the fake client received."""
    calls: list = []
    monkeypatch.setattr(gfw, "_client", lambda: FakeClient(calls))
    monkeypatch.setattr(gfw, "_settings", lambda: SETTINGS)
    monkeypatch.setattr(gfw, "_run", lambda result: result)  # fake calls are plain, not coroutines
    return calls
