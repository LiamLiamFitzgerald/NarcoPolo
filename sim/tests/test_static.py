# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportOperatorIssue=false, reportCallIssue=false
import json
import struct

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import shape

from core.config import load
from core.crs import to_utm
from core.io import CONFIG_PATH
from sim.simulate import _make_map
from sim.static import PIXEL_M, write_static
from sim.world import SimWorld

FILES = [
    "osm_piers.geojson",
    "coastline.gpkg",
    "inshore/inshore_grounds.gpkg",
    "inshore/survey_extent.gpkg",
    "infomar_bathy.tif",
]


def world():
    cfg, _ = load(CONFIG_PATH)
    m = _make_map(cfg)
    return SimWorld(cfg, 1, None, 0, m["fine"], None, None, None, None, None)  # type: ignore[arg-type]  # static layers read only config


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_RAW", str(tmp_path / "a"))
    write_static(world())
    return tmp_path / "a"


def test_piers_round_trip_through_core_crs(raw):
    feats = json.loads((raw / "osm_piers.geojson").read_text())["features"]
    assert len(feats) == 6 and sum(f["properties"]["road_access"] == "yes" for f in feats) == 4
    lon, lat = zip(*(shape(f["geometry"]).coords[0] for f in feats), strict=True)
    x, y = to_utm(lon, lat)
    truth = _make_map(world().config)["piers"].geometry
    assert np.allclose(x, truth.x, atol=0.5) and np.allclose(y, truth.y, atol=0.5)


def test_inshore_polygon_covers_cells_with_inshore_frac(raw):
    band = gpd.read_file(raw / "inshore" / "inshore_grounds.gpkg").to_crs(32629).geometry.iloc[0]
    fine = world().fine
    hit = fine["geometry"].apply(band.intersects)
    assert (hit == (fine["inshore_frac"] > 0)).all()
    sea = gpd.read_file(raw / "coastline.gpkg").to_crs(32629).geometry.iloc[0]
    assert band.bounds[3] == pytest.approx(sea.bounds[1], abs=0.5)  # the band stops at the shore
    extent = gpd.read_file(raw / "inshore" / "survey_extent.gpkg").to_crs(32629).geometry.iloc[0]
    assert extent.buffer(1).contains(band)


def test_bathymetry_header_and_depth(raw):
    b = (raw / "infomar_bathy.tif").read_bytes()
    assert b[:4] == b"II*\x00"
    n = struct.unpack_from("<H", b, 8)[0]
    tags = {t: v for t, _, _, v in (struct.unpack_from("<HHII", b, 10 + 12 * i) for i in range(n))}
    w, h = tags[256], tags[257]
    depth = np.frombuffer(b, "<f4", w * h, tags[273]).reshape(h, w)
    assert (
        depth.max() == 0 and depth[-1, 0] < depth[0, 0]
    )  # row 0 is the shore (north); deeper to the south
    assert struct.unpack_from("<2d", b, tags[33550])[0] == PIXEL_M


def test_same_inputs_give_identical_bytes(raw, tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_RAW", str(tmp_path / "b"))
    write_static(world())
    for f in FILES:
        if f.endswith(
            ".gpkg"
        ):  # SQLite keeps a write counter in its header, so compare what the file holds
            a, b = (gpd.read_file(r / f) for r in (raw, tmp_path / "b"))
            assert a.geometry.equals(b.geometry), f
        else:
            assert (raw / f).read_bytes() == (tmp_path / "b" / f).read_bytes(), f
