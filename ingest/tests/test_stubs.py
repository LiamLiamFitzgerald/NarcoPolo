"""Every offline stub (era5, osm are real; static is real once its URLs are configured: tests/test_*.py) writes the raw/ shape the simulator writes, records it with a licence, and opens no socket."""

import json
import socket
import struct
from datetime import date

import pandas as pd
import pyarrow.parquet as pq
import pyogrio
import pytest

from ingest import era5, fetch_all, gfw, osm, probe, s1, static
from ingest.tests.conftest import CFG, FakeCDS

B = CFG["region_bbox"]
BBOX = (B["lon_min"], B["lat_min"], B["lon_max"], B["lat_max"])
START, END = date(2026, 11, 1), date(2026, 11, 3)


@pytest.fixture(autouse=True)
def raw(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("stub opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setenv("NARCO_RAW", str(tmp_path))
    return tmp_path


def _files(raw):
    return json.loads((raw / "manifest.json").read_text())["files"]


def _recorded(raw, path):
    entry = _files(raw)[path.relative_to(raw).as_posix()]
    assert entry["licence"].strip() and entry["request"]["stub"] is True


def _tiff_tags(path):
    """{tag: values} from the first IFD of a little-endian TIFF."""
    b = path.read_bytes()
    (ifd,) = struct.unpack_from("<I", b, 4)
    (n,) = struct.unpack_from("<H", b, ifd)
    fmt, size, tags = {3: "H", 4: "I", 12: "d"}, {3: 2, 4: 4, 12: 8}, {}
    for i in range(n):
        tag, typ, count = struct.unpack_from("<HHI", b, ifd + 2 + 12 * i)
        at = ifd + 2 + 12 * i + 8
        if size[typ] * count > 4:
            (at,) = struct.unpack_from("<I", b, at)
        tags[tag] = list(struct.unpack_from(f"<{count}{fmt[typ]}", b, at))
    return tags


def _same_raster_shape(stub, simulated):
    a, s = _tiff_tags(stub), _tiff_tags(simulated)
    for tag in (258, 339, 34735):  # bits per band, sample format, GeoKeys (EPSG:32629)
        assert a[tag] == s[tag], tag
    assert a.get(277, [1]) == s.get(277, [1])  # band count


def _same_gpkg_shape(stub, simulated, layer):
    a, s = pyogrio.read_info(stub, layer=layer), pyogrio.read_info(simulated, layer=layer)
    assert a["geometry_type"] == s["geometry_type"] and a["crs"] == s["crs"]
    assert list(a["fields"]) == list(s["fields"]) and a["features"] == 0


def test_probe_reports_no_go_without_network():
    s1_ok, gfw_ok, notes = probe.probe()
    assert (s1_ok, gfw_ok) == (False, False) and "stub" in notes


def test_list_passes_columns():
    passes = s1.list_passes(BBOX, START, END)
    assert list(passes.columns) == ["pass_id", "time", "orbit_dir", "rel_orbit", "footprint"]
    assert len(passes) == 0


def test_select_passes_adds_downloaded_flag(simraw):
    passes = pd.DataFrame({"pass_id": ["pass_000", "pass_001"]})
    out = s1.select_passes(passes, simraw / "era5.nc")
    assert list(out["pass_id"]) == ["pass_000", "pass_001"]
    assert out["downloaded"].dtype == bool and not out["downloaded"].any()


def test_fetch_scene_matches_simulator(simraw, raw):
    sim_tif = min((simraw / "s1").glob("*.tif"))
    sim_meta = json.loads(sim_tif.with_suffix(".json").read_text())
    row = {
        "pass_id": sim_meta["pass_id"],
        "time": pd.Timestamp(sim_meta["start_time"]),
        "orbit_dir": sim_meta["orbit_direction"],
        "rel_orbit": sim_meta["relative_orbit"],
        "footprint": sim_meta["footprint"],
    }
    tif = s1.fetch_scene(row)
    assert tif.parent == raw / "s1" and tif.suffix == ".tif"
    _same_raster_shape(tif, sim_tif)
    assert _tiff_tags(tif)[33550] == _tiff_tags(sim_tif)[33550]  # 10 m pixels
    meta = json.loads(tif.with_suffix(".json").read_text())
    assert set(meta) == set(sim_meta)
    assert meta["start_time"] == pd.Timestamp(sim_meta["start_time"]).isoformat()
    _recorded(raw, tif)
    _recorded(raw, tif.with_suffix(".json"))
    assert s1.fetch_scene(row) == tif  # cache hit


@pytest.mark.parametrize(
    "fn, name", [(gfw.fetch_sar, "gfw_sar"), (gfw.fetch_presence, "gfw_presence")]
)
def test_gfw_matches_simulator_schema(simraw, raw, fn, name):
    path = fn(BBOX, START, END)
    assert path == raw / f"{name}.parquet"
    sim_schema = pq.read_schema(simraw / f"{name}.parquet").remove_metadata()
    assert pq.read_schema(path).remove_metadata().equals(sim_schema)
    assert pq.read_metadata(path).num_rows == 0  # nothing downloaded, never a fake zero
    _recorded(raw, path)


def test_fetch_inshore_matches_simulator(simraw, raw):
    paths = static.fetch_inshore()
    assert {p.relative_to(raw).as_posix() for p in paths} == {
        p.relative_to(simraw).as_posix() for p in (simraw / "inshore").glob("*.gpkg")
    }
    for p in paths:
        _same_gpkg_shape(p, simraw / "inshore" / p.name, p.stem)
        _recorded(raw, p)


def test_fetch_bathy_matches_simulator(simraw, raw):
    path = static.fetch_bathy()
    _same_raster_shape(path, simraw / "infomar_bathy.tif")
    _recorded(raw, path)


def test_fetch_all_records_everything_and_is_idempotent(simraw, raw, monkeypatch):
    monkeypatch.setattr(era5, "_client", lambda: FakeCDS(simraw / "era5.nc"))
    monkeypatch.setattr(osm, "_overpass", lambda q: {"elements": []})
    fetch_all(CFG)
    on_disk = {p.relative_to(raw).as_posix() for p in raw.rglob("*") if p.is_file()} - {
        "manifest.json"
    }
    files = _files(raw)
    assert on_disk == set(files) and on_disk >= {"era5.nc", "gfw_sar.parquet", "coastline.gpkg"}
    assert all(e["licence"].strip() for e in files.values())
    fetch_all(CFG)
    assert _files(raw) == files  # second run downloads (and re-records) nothing
