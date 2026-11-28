"""fetch_era5 against a fake CDS that serves the simulator's ERA5: the file it writes must equal the simulator's hours."""

import json
import socket
from datetime import date

import netCDF4
import numpy as np
import pytest

from ingest import era5
from ingest.tests.conftest import CFG, FakeCDS

B = CFG["region_bbox"]
BBOX = (B["lon_min"], B["lat_min"], B["lon_max"], B["lat_max"])


@pytest.fixture(autouse=True)
def raw(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setenv("NARCO_RAW", str(tmp_path))
    return tmp_path


def _sim_window(simraw):
    """Two days either side of a month boundary inside the simulated period."""
    with netCDF4.Dataset(simraw / "era5.nc") as s:
        when = np.asarray(netCDF4.num2date(s["time"][:], s["time"].units))
    y, m = max({(w.year, w.month) for w in when})  # the last month starts inside the period
    first = date(y, m, 1)
    return date.fromordinal(first.toordinal() - 2), date.fromordinal(first.toordinal() + 1)


def _fake(monkeypatch, simraw, split=False):
    fake = FakeCDS(simraw / "era5.nc", split)
    monkeypatch.setattr(era5, "_client", lambda: fake)
    return fake


@pytest.mark.parametrize("split", [False, True])
def test_fetch_era5_recovers_simulator_hours(simraw, raw, monkeypatch, split):
    start, end = _sim_window(simraw)
    fake = _fake(monkeypatch, simraw, split)
    path = era5.fetch_era5(BBOX, start, end)
    assert path == raw / "era5.nc"
    with netCDF4.Dataset(path) as a, netCDF4.Dataset(simraw / "era5.nc") as s:
        st = s["time"][:]
        when = np.asarray(netCDF4.num2date(st, s["time"].units))
        keep = np.array([start <= date(w.year, w.month, w.day) <= end for w in when])
        assert a["time"].units == s["time"].units
        assert (
            list(a["time"][:]) == list(st[keep]) and len(a["time"]) == 4 * 24
        )  # UTC hours, no gaps
        assert list(a["latitude"][:]) == list(s["latitude"][:])
        assert list(a["longitude"][:]) == list(s["longitude"][:])
        for v in ("u10", "v10", "swh"):
            assert a[v].dimensions == s[v].dimensions and a[v].units == s[v].units
            got, want = np.ma.filled(a[v][:], np.nan), np.asarray(s[v][:])[keep]
            if v == "swh":  # the fake's missing land point stays NaN, never 0
                assert np.isnan(got[0, 0, 0])
                got[0, 0, 0] = want[0, 0, 0]
            np.testing.assert_array_equal(got, want)
    assert len(fake.calls) == 2  # one per calendar month


def test_requests_stay_inside_window_and_region(simraw, raw, monkeypatch):
    start, end = _sim_window(simraw)
    fake = _fake(monkeypatch, simraw)
    era5.fetch_era5(BBOX, start, end)
    (d1, r1), (d2, r2) = fake.calls
    assert d1 == d2 == "reanalysis-era5-single-levels"
    assert len(r1["day"]) + len(r2["day"]) == 4 and r1["month"] != r2["month"]
    assert r1["area"] == [B["lat_max"], B["lon_min"], B["lat_min"], B["lon_max"]]
    assert r1["time"] == [f"{h:02d}:00" for h in range(24)]
    assert set(r1["variable"]) == {
        "10m_u_component_of_wind",
        "10m_v_component_of_wind",
        "significant_height_of_combined_wind_waves_and_swell",
    }


def test_rerun_downloads_nothing(simraw, raw, monkeypatch):
    start, end = _sim_window(simraw)
    fake = _fake(monkeypatch, simraw)
    path = era5.fetch_era5(BBOX, start, end)
    entry = json.loads((raw / "manifest.json").read_text())["files"]["era5.nc"]
    assert "Copernicus" in entry["licence"] and entry["request"]["requests"] == [
        c[1] for c in fake.calls
    ]
    monkeypatch.setattr(era5, "_client", lambda: pytest.fail("cached request hit the network"))
    assert era5.fetch_era5(BBOX, start, end) == path
    assert {p.name for p in raw.iterdir()} == {"era5.nc", "manifest.json"}  # temp parts cleaned up


def test_different_grids_fail_loudly(simraw, raw, monkeypatch):
    start, end = _sim_window(simraw)
    _fake(monkeypatch, simraw)
    real_read = era5._read

    def shifted(path):
        part = real_read(path)
        if part["time"][0] > 0 and "swh" in part["vars"]:
            part["longitude"] = part["longitude"] + 0.25
        return part

    calls = iter([False, True])
    monkeypatch.setattr(era5, "_read", lambda p: shifted(p) if next(calls) else real_read(p))
    with pytest.raises(ValueError, match="grids"):
        era5.fetch_era5(BBOX, start, end)
    assert not (raw / "manifest.json").exists()
