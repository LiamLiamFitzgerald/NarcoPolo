"""ingest.s1 against fakes of the CDSE catalogue and openEO that serve the simulator's passes and scenes."""

import json
import socket
from datetime import date, timedelta

import netCDF4
import numpy as np
import pandas as pd
import pytest
import rasterio
import shapely
from openeo.dates import get_temporal_extent
from pyproj import Transformer
from shapely.geometry import box, mapping

from ingest import s1
from ingest.tests.conftest import CFG

B = CFG["region_bbox"]
BBOX = (B["lon_min"], B["lat_min"], B["lon_max"], B["lat_max"])
TO_LL = Transformer.from_crs(32629, 4326, always_xy=True)


@pytest.fixture(autouse=True)
def raw(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setenv("NARCO_RAW", str(tmp_path))
    monkeypatch.setattr(s1, "_conn", None)
    return tmp_path


def _sim_scenes(simraw):
    return [json.loads(p.read_text()) for p in sorted((simraw / "s1").glob("*.json"))]


def _products(scenes):
    """Each simulated pass as two 25 s catalogue slices (north and south half of its footprint), in WGS84."""
    out = []
    for k, m in enumerate(scenes):
        fp = shapely.transform(
            shapely.from_wkt(m["footprint"]),
            lambda c: np.column_stack(TO_LL.transform(c[:, 0], c[:, 1])),
        )
        x0, y0, x1, y1 = fp.bounds
        t0 = pd.Timestamp(m["start_time"])
        for i, half in enumerate((box(x0, (y0 + y1) / 2, x1, y1), box(x0, y0, x1, (y0 + y1) / 2))):
            start = t0 + pd.Timedelta(seconds=25 * i)
            out.append(
                {
                    "Name": f"slice{k}_{i}",
                    "ContentDate": {
                        "Start": start.isoformat(),
                        "End": (start + pd.Timedelta(seconds=25)).isoformat(),
                    },
                    "GeoFootprint": mapping(half),
                    "Attributes": [
                        {"Name": "platformSerialIdentifier", "Value": "A"},
                        {"Name": "orbitNumber", "Value": 1000 + k},
                        {"Name": "orbitDirection", "Value": m["orbit_direction"]},
                        {"Name": "relativeOrbitNumber", "Value": m["relative_orbit"]},
                    ],
                }
            )
    return out


@pytest.fixture
def catalogue(simraw, monkeypatch):
    """Serves the simulator's passes in two pages; returns the list of (url, params) calls."""
    products, calls = _products(_sim_scenes(simraw)), []
    half = len(products) // 2

    def get(url, params):
        calls.append((url, params))
        if params is None:
            return {"value": products[half:]}
        return {"value": products[:half], "@odata.nextLink": "next-page"}

    monkeypatch.setattr(s1, "_catalogue", get)
    return calls


def test_list_passes_recovers_simulated_passes(simraw, raw, catalogue):
    scenes = _sim_scenes(simraw)
    out = s1.list_passes(BBOX, date(2000, 1, 1), date(2100, 1, 1))
    assert list(out.columns) == [
        "pass_id",
        "time",
        "orbit_dir",
        "rel_orbit",
        "footprint",
        "end_time",
        "heading_deg",
    ]
    assert len(out) == len(scenes)  # two slices each, one pass
    want = sorted(pd.Timestamp(m["start_time"]) for m in scenes)
    assert list(out["time"]) == want and str(out["time"].dt.tz) == "UTC"
    assert ((out["end_time"] - out["time"]) == pd.Timedelta(seconds=50)).all()
    first = min(scenes, key=lambda m: m["start_time"])
    fp = shapely.transform(
        shapely.from_wkt(first["footprint"]),
        lambda c: np.column_stack(TO_LL.transform(c[:, 0], c[:, 1])),
    )
    assert shapely.from_wkt(out["footprint"].iloc[0]).buffer(1e-9).contains(fp)  # union of slices
    url, params = catalogue[0]
    assert url == s1.CATALOGUE_URL and "IW_GRDH_1S" in params["$filter"]
    assert "ContentDate/Start lt 2100-01-02T00:00:00.000Z" in params["$filter"]  # end day included
    entry = json.loads((raw / "manifest.json").read_text())["files"]
    assert any(
        k.startswith("s1_catalogue/") and "Copernicus" in v["licence"] for k, v in entry.items()
    )
    n = len(catalogue)
    s1.list_passes(BBOX, date(2000, 1, 1), date(2100, 1, 1))
    assert len(catalogue) == n  # rerun: answered from the cache


def _era5(path, hours, calm_lon):
    """A 3 x 3 ERA5 grid over the region; at each hour the points west of calm_lon[hour] are calm.
    One point is land (wave height missing) and calm, so it must not count."""
    lat = np.array([51.2, 51.5, 51.8])
    lon = np.array([-10.0, -9.0, -8.0])
    with netCDF4.Dataset(path, "w") as nc:
        for name, data in (("time", None), ("latitude", lat), ("longitude", lon)):
            nc.createDimension(name, len(hours) if data is None else len(data))
        t = nc.createVariable("time", "i4", ("time",))
        t.units = "hours since 1900-01-01 00:00:00.0"
        t[:] = netCDF4.date2num([h.to_pydatetime() for h in hours], t.units)
        nc.createVariable("latitude", "f4", ("latitude",))[:] = lat
        nc.createVariable("longitude", "f4", ("longitude",))[:] = lon
        calm = np.array([[lon < c for _ in lat] for c in calm_lon])
        wind = np.where(calm, 2.0, 12.0)
        hs = np.ma.masked_invalid(np.where(calm, 0.5, 3.0))
        hs[:, 2, 2] = np.ma.masked  # land
        for n, d in (("u10", wind), ("v10", np.zeros_like(wind)), ("swh", hs)):
            nc.createVariable(n, "f4", ("time", "latitude", "longitude"), fill_value=-9999.0)[:] = d


def test_select_passes_calm_share_and_rough_spread(raw, tmp_path):
    hours = pd.date_range("2026-11-01", periods=10, freq="D", tz="UTC") + pd.Timedelta(hours=6)
    # calm share over the 8 sea points: all calm, 6/8, 3/8 (rough), and 7 fully rough passes
    calm_lon = [0.0, -8.5, -9.5] + [-99.0] * 7
    _era5(tmp_path / "era5.nc", hours, calm_lon)
    passes = pd.DataFrame(
        {
            "pass_id": [f"p{i}" for i in range(10)],
            "time": hours + pd.Timedelta(minutes=20),  # nearest hour is 06:00 UTC
            "orbit_dir": "DESCENDING",
            "rel_orbit": 1,
            "footprint": box(*BBOX).wkt,
        }
    )
    passes.loc[9, "footprint"] = box(
        0, 0, 1, 1
    ).wkt  # covers no region point: unknown, never chosen
    out = s1.select_passes(passes, tmp_path / "era5.nc")
    assert out["calm_share"].iloc[:3].tolist() == [1.0, 0.75, 0.375] and np.isnan(
        out["calm_share"][9]
    )
    assert out["downloaded"].dtype == bool
    calm = ["p0", "p1"]
    rough = [
        "p2",
        "p4",
        "p5",
        "p6",
        "p8",
    ]  # 7 rough candidates p2..p8, 5 spread: first, last, between
    assert sorted(out.loc[out["downloaded"], "pass_id"]) == sorted(calm + rough)
    saved = json.loads((raw / "s1_passes.json").read_text())
    assert [r["pass_id"] for r in saved] == list(passes["pass_id"])  # every pass, downloaded or not
    assert saved[9]["calm_share"] is None
    files = json.loads((raw / "manifest.json").read_text())["files"]
    before = files["s1_passes.json"]
    s1.select_passes(passes, tmp_path / "era5.nc")
    assert json.loads((raw / "manifest.json").read_text())["files"]["s1_passes.json"] == before


def test_select_passes_without_era5_hour_selects_nothing(raw, tmp_path):
    hours = pd.date_range("2026-11-01", periods=2, freq="h", tz="UTC")
    _era5(tmp_path / "era5.nc", hours, [0.0, 0.0])
    passes = pd.DataFrame(
        {"pass_id": ["late"], "time": [hours[-1] + pd.Timedelta(hours=3)], "orbit_dir": "A",
         "rel_orbit": 1, "footprint": [box(*BBOX).wkt]}
    )  # fmt: skip
    out = s1.select_passes(passes, tmp_path / "era5.nc")
    assert not out["downloaded"].any() and np.isnan(out["calm_share"][0])


class FakeCube:
    """openEO DataCube stand-in: records the chain; the batch job writes the simulator chip as linear sigma0."""

    def __init__(self, calls, sim_tif, shift_m=0.0):
        self.calls, self.sim_tif, self.shift_m = calls, sim_tif, shift_m

    def load_collection(self, collection_id, **kw):
        self.calls.append(("load_collection", collection_id, kw))
        get_temporal_extent(extent=kw["temporal_extent"])  # the real client's date check
        return self

    def sar_backscatter(self, **kw):
        self.calls.append(("sar_backscatter", kw))
        return self

    def resample_spatial(self, **kw):
        self.calls.append(("resample_spatial", kw))
        return self

    def execute_batch(self, outputfile, out_format, **kw):
        self.calls.append(("execute_batch", out_format))
        with rasterio.open(self.sim_tif) as s:
            db = s.read().astype(np.float64)
            profile = {**s.profile, "dtype": "float32", "nodata": None, "driver": "GTiff"}
            t = s.transform
            profile["transform"] = rasterio.Affine(t.a, t.b, t.c + self.shift_m, t.d, t.e, t.f)
        lin = (10.0 ** (db / 1000.0)).astype(np.float32)
        lin[:, 0, 0] = np.nan  # outside the swath
        with rasterio.open(outputfile, "w", **profile) as w:
            w.write(lin)


def _row(meta):
    t = pd.Timestamp(meta["start_time"]) + pd.Timedelta(
        microseconds=54368
    )  # as the catalogue gives
    return {
        "pass_id": meta["pass_id"], "time": t, "end_time": t + pd.Timedelta(seconds=50),
        "orbit_dir": meta["orbit_direction"], "rel_orbit": meta["relative_orbit"],
        "footprint": "POLYGON ((-10 51, -8 51, -8 52, -10 52, -10 51))",
    }  # fmt: skip


def test_fetch_scene_recovers_simulator_chip(simraw, raw, monkeypatch):
    sim_tif = min((simraw / "s1").glob("*.tif"))
    sim_meta = json.loads(sim_tif.with_suffix(".json").read_text())
    calls = []
    monkeypatch.setattr(s1, "_connection", lambda: FakeCube(calls, sim_tif))
    row = _row(sim_meta)
    tif = s1.fetch_scene(row)
    assert tif.parent == raw / "s1" and tif.suffix == ".tif"
    with rasterio.open(tif) as a, rasterio.open(sim_tif) as s:
        assert a.dtypes == ("int16", "int16") and a.nodata == -32768
        assert a.transform == s.transform and a.crs.to_epsg() == 32629
        got, want = a.read(), s.read()
    assert (got[:, 0, 0] == -32768).all()  # no backscatter stays nodata, never 0
    got[:, 0, 0] = want[:, 0, 0]
    assert np.abs(got.astype(int) - want).max() <= 1  # dB x 100 round trip through linear float32
    (_, coll, kw), (_, bs), (_, rs), (_, fmt) = calls
    assert coll == "SENTINEL1_GRD" and kw["bands"] == ["VV", "VH"]
    z = lambda t: t.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    assert kw["temporal_extent"] == [  # whole seconds around the fractional pass times
        z(row["time"].floor("s")),
        z(row["end_time"].ceil("s") + timedelta(seconds=1)),
    ]
    ext = kw["spatial_extent"]
    assert ext["crs"] == 32629 and all((ext[k] - CFG["x0"]) % 10 == 0 for k in ("west", "east"))
    assert all((ext[k] - CFG["y0"]) % 10 == 0 for k in ("south", "north"))
    assert bs == {"coefficient": "sigma0-ellipsoid"} and rs == {
        "resolution": 10.0,
        "projection": 32629,
    }
    assert fmt == "GTiff"
    meta = json.loads(tif.with_suffix(".json").read_text())
    assert (
        set(meta) == set(sim_meta) and meta["prf_hz"] is None and meta["heading_deg"] is None
    )  # no heading given
    assert meta["start_time"] == row["time"].isoformat()
    files = json.loads((raw / "manifest.json").read_text())["files"]
    for p in (tif, tif.with_suffix(".json")):
        assert "Copernicus" in files[p.relative_to(raw).as_posix()]["licence"]
    assert {p.name for p in (raw / "s1").iterdir()} == {tif.name, tif.with_suffix(".json").name}
    monkeypatch.setattr(s1, "_connection", lambda: pytest.fail("cached scene hit openEO"))
    assert s1.fetch_scene(row) == tif


def test_fetch_scene_off_grid_fails_and_records_nothing(simraw, raw, monkeypatch):
    sim_tif = min((simraw / "s1").glob("*.tif"))
    meta = json.loads(sim_tif.with_suffix(".json").read_text())
    monkeypatch.setattr(s1, "_connection", lambda: FakeCube([], sim_tif, shift_m=5.0))
    with pytest.raises(ValueError, match="grid"):
        s1.fetch_scene(_row(meta))
    assert not (raw / "manifest.json").exists()


def test_parallel_fetches_share_one_openeo_login(monkeypatch):
    """ingest/run calls fetch_scene from several threads (#33); the device login must happen once."""
    import sys
    import threading
    import time
    import types

    logins = []

    class FakeConnection:
        def authenticate_oidc(self, **_):
            logins.append(1)
            time.sleep(0.05)  # a slow device login: other threads arrive while it runs
            return self

    monkeypatch.setitem(
        sys.modules, "openeo", types.SimpleNamespace(connect=lambda url: FakeConnection())
    )
    got, start = [], threading.Barrier(8)

    def worker():
        start.wait()
        got.append(s1._connection())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(logins) == 1 and len({id(c) for c in got}) == 1


def test_heading_is_the_bearing_from_first_to_last_slice():
    """#291: the fake catalogue's slices go north half first, then south: a descending track, about 180 deg.
    The same slices in reverse time order fly north (about 0 deg); one slice gives no heading (NaN, never 0)."""
    north, south = box(-9.0, 51.5, -8.0, 52.0), box(-9.0, 51.0, -8.0, 51.5)
    t0 = pd.Timestamp("2026-11-22T06:47:00Z")
    t1 = t0 + pd.Timedelta(seconds=25)
    assert abs(s1._heading([t0, t1], [north, south]) - 180.0) < 1.0
    assert (
        s1._heading([t1, t0], [north, south]) < 1.0 or s1._heading([t1, t0], [north, south]) > 359.0
    )
    assert np.isnan(s1._heading([t0], [north]))


def test_list_passes_heading_on_simulated_passes(simraw, raw, catalogue):
    out = s1.list_passes(BBOX, date(2000, 1, 1), date(2100, 1, 1))
    assert ((out["heading_deg"] - 180.0).abs() < 1.0).all()  # every fake pass flies north to south


def test_fetch_scene_writes_the_measured_heading(simraw, raw, monkeypatch):
    sim_tif = min((simraw / "s1").glob("*.tif"))
    meta = json.loads(sim_tif.with_suffix(".json").read_text())
    monkeypatch.setattr(s1, "_connection", lambda: FakeCube([], sim_tif))
    tif = s1.fetch_scene(_row(meta) | {"heading_deg": 193.456})
    assert json.loads(tif.with_suffix(".json").read_text())["heading_deg"] == 193.46
    assert s1._float_or_none(float("nan")) is None and s1._float_or_none(None) is None
