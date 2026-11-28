import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.io import netcdf_file

import sim.simulate
from core import io
from core.config import load, snapshot_date
from sim.raw import write_raw


def run(tmp: Path, mp: pytest.MonkeyPatch, seed: int = 20261127):
    """simulate() into tmp; returns the raw root and the SimWorld write_raw saw."""
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    mp.setenv("NARCO_RAW", str(tmp / "raw"))
    cfg_path = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg_path)
    mp.setattr(io, "CONFIG_PATH", cfg_path)
    seen = []
    mp.setattr(sim.simulate, "write_raw", lambda w: (seen.append(w), write_raw(w)))
    sim.simulate.simulate(load(cfg_path)[0], seed)
    return tmp / "raw", seen[0]


@pytest.fixture(scope="module")
def raw(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    yield run(tmp_path_factory.mktemp("a"), mp)
    mp.undo()


def _hashes(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def test_same_seed_same_bytes(raw, tmp_path_factory):
    root, _ = raw
    mp = pytest.MonkeyPatch()
    other, _ = run(tmp_path_factory.mktemp("b"), mp)
    mp.undo()
    first = _hashes(root)
    assert {"gfw_sar.parquet", "gfw_presence.parquet", "era5.nc", "manifest.json"} <= set(first)
    assert first == _hashes(other)


def test_era5_wind_and_waves_match_world_weather(raw):
    root, world = raw
    with netcdf_file(root / "era5.nc", "r", mmap=False) as f:
        u, v, swh = (f.variables[k][:].copy() for k in ("u10", "v10", "swh"))
        lat, lon = f.variables["latitude"][:].copy(), f.variables["longitude"][:].copy()
        assert len(f.variables["time"][:]) == world.days * 24
    assert np.allclose(np.diff(lon), 0.25) and np.allclose(np.diff(lat), -0.25)
    daily = np.hypot(u, v).reshape(world.days, 24, -1).mean(axis=(1, 2))
    assert np.allclose(daily, world.weather["wind_ms"], atol=1e-4)
    sea = ~np.isnan(swh[0])
    assert sea.any() and not sea.all()  # land points carry no wave height (A8)
    assert np.allclose(swh[::24][:, sea].mean(axis=1), world.weather["hs_m"], atol=1e-4)


def test_manifest_lists_every_file_and_gives_T(raw):
    root, _ = raw
    m = json.loads((root / "manifest.json").read_text())
    on_disk = {k: h for k, h in _hashes(root).items() if k != "manifest.json"}
    assert {k: e["sha256"] for k, e in m["files"].items()} == on_disk
    assert all(
        {"request", "sha256", "download_time", "licence"} <= set(e) for e in m["files"].values()
    )
    assert snapshot_date(m) == io.read_snapshot()["T"]


def test_gfw_sar_and_presence(raw):
    root, world = raw
    sar = pd.read_parquet(root / "gfw_sar.parquet")
    assert sar["matched"].any() and set(sar["scene_id"]) <= set(world.passes["pass_id"])
    pres = pd.read_parquet(root / "gfw_presence.parquet")
    assert (pres["hours"] > 0).all()  # only cells with presence, never a stored zero
    assert {"vessel_type", "speed_bin", "date", "lon", "lat"} <= set(pres.columns)
    slow = pres[pres["speed_bin"] == "0-2"]["hours"].sum()
    assert (
        abs(slow - world.ships["duration_min"].sum() / 60) < 1
    )  # every slowdown shows as slow hours


def test_presence_2km_holds_the_raw_presence_hours(raw):  # #208
    root, world = raw
    pres = pd.read_parquet(root / "gfw_presence.parquet")
    p2 = io.read_stage("reference/presence_2km")
    assert set(p2["cell_id"]) <= set(world.fine["cell_id"])
    keys = ["date", "vessel_type", "speed_bin"]
    raw_h = pres.assign(date=pd.to_datetime(pres["date"])).groupby(keys)["hours"].sum()
    assert (p2.groupby(keys)["hours"].sum() - raw_h).abs().max() < 0.01  # raw rounds to 3 dp
    assert (p2["hours"] > 0).all() and set(p2["speed_bin"]) == set(pres["speed_bin"])


def test_simulate_refuses_a_raw_folder_with_real_downloads(tmp_path, monkeypatch):  # #331
    raw = tmp_path / "raw"
    (raw / "gfw").mkdir(parents=True)
    (raw / "gfw_presence.parquet").write_bytes(b"real")
    entry = {
        "request": {"dataset": "presence"},
        "sha256": "x",
        "download_time": "t",
        "licence": "l",
    }
    (raw / "manifest.json").write_text(json.dumps({"files": {"gfw_presence.parquet": entry}}))
    before = _hashes(raw)
    monkeypatch.setenv("NARCO_RAW", str(raw))
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    with pytest.raises(RuntimeError, match="real files"):
        sim.simulate.simulate(load(io.CONFIG_PATH)[0], 1)
    assert _hashes(raw) == before
    assert not (tmp_path / "data").exists()
