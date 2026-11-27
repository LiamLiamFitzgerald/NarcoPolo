"""reference/piers (#36): road access, a closed sea raster, and sea-only travel times around headlands."""

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry

from core import io
from core.config import load
from core.grid import FINE, _origin
from reference import piers as rp
from sim.simulate import simulate

KN = 0.514444


def _x0y0() -> tuple[float, float]:
    return _origin()


def test_road_access_within_200_m_and_names_kept():
    x0, y0 = _x0y0()
    osm = gpd.GeoDataFrame(
        {"name": ["Harbour A", None], "man_made": ["pier", "pier"]},
        geometry=[Point(x0 + 5000, y0 + 5000), Point(x0 + 9000, y0 + 5000)],
        crs=32629,
    )
    roads = gpd.GeoDataFrame(
        geometry=[LineString([(x0 + 5150, y0), (x0 + 5150, y0 + 9000)])], crs=32629
    )
    p = rp.piers(osm, roads)
    assert list(p["road_access"]) == [True, False]  # 150 m away vs 3.85 km away
    assert p["name"].iloc[0] == "Harbour A" and p["name"].isna().iloc[1]  # never invented


def test_piers_keep_only_pier_slipway_harbour_tags_and_reproject():
    osm = gpd.GeoDataFrame(
        {
            "man_made": ["pier", None, None, "lighthouse"],
            "leisure": [None, "slipway", None, None],
            "harbour": [None, None, "yes", None],
            "name": ["a", "b", "c", "d"],
        },
        geometry=[Point(-8.5, 51.6), Point(-8.4, 51.6), Point(-8.3, 51.6), Point(-8.2, 51.6)],
        crs=4326,
    )
    p = rp.piers(osm, gpd.GeoDataFrame(geometry=[], crs=32629))
    assert list(p["name"]) == ["a", "b", "c"]
    assert (
        p.crs is not None and p.crs.to_epsg() == 32629 and p.geometry.x.min() > 100_000
    )  # metres, not degrees


def _headland() -> tuple[BaseGeometry, Point, Point]:
    """Straight shore along the top with a 10 km headland sticking south; a pier west of it, a spot east of it."""
    x0, y0 = _x0y0()
    land = box(x0, y0 + 20_000, x0 + 40_000, y0 + 30_000).union(
        box(x0 + 19_000, y0 + 10_000, x0 + 21_000, y0 + 20_000)
    )
    return land, Point(x0 + 15_000, y0 + 19_500), Point(x0 + 25_000, y0 + 19_000)


def test_travel_goes_around_the_headland():
    land, pier, spot = _headland()
    sea = rp.sea_raster(land)
    rp.assert_closed(sea)
    p = gpd.GeoDataFrame(
        {"pier_id": ["pier_0"], "name": [None], "road_access": [True]}, geometry=[pier], crs=32629
    )
    th = rp.travel_hours(sea, p).set_index("cell_id")["hours"]
    x0, y0 = _x0y0()
    cid = f"2000_{int((spot.x - x0) // FINE)}_{int((spot.y - y0) // FINE)}"
    straight_h = pier.distance(spot) / (15 * KN) / 3600
    assert th[cid] > 2 * straight_h  # 10 km straight; ~2 x 10 km around the headland tip


def test_travel_hours_never_beat_a_straight_line_on_the_simulator(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("NARCO_RAW", str(tmp_path / "raw"))
    simulate(load(io.CONFIG_PATH)[0], 20261127)
    sim_piers = gpd.GeoDataFrame(io.read_stage("reference/piers"), crs=32629)
    cells = io.read_stage("reference/cells").query("level == 2000")
    x0, y0 = _x0y0()
    top = y0 + (cells["cell_id"].str.split("_").str[2].astype(int).max()) * FINE + 0.6 * FINE
    land = box(x0 - 1000, top, x0 + 200_000, top + 50_000)  # the simulator's straight shore line
    th = rp.travel_hours(rp.sea_raster(land), sim_piers)
    assert set(th["pier_id"]) == set(sim_piers.loc[sim_piers["road_access"], "pier_id"])
    xy = sim_piers.set_index("pier_id").geometry
    s = th.sample(200, random_state=1)
    for cid, pid, hours in zip(s["cell_id"], s["pier_id"], s["hours"], strict=True):
        _, i, j = (int(v) for v in str(cid).split("_"))
        c = Point(x0 + (i + 0.5) * FINE, y0 + (j + 0.5) * FINE)
        # the path ends at the cell's sea pixel nearest its centre, so allow half a cell and a pixel
        assert hours >= (xy[pid].distance(c) - FINE / 2 - 250) / (15 * KN) / 3600


def test_assert_closed_catches_a_diagonal_leak():
    sea = np.ones((5, 5), np.uint8)
    sea[2, :] = 0  # a land wall across the raster
    rp.assert_closed(sea)  # closed: two separate seas is fine
    sea[2, 2] = 1  # a gap in the wall
    rp.assert_closed(sea)  # a real channel is open water, not a leak
    sea = np.ones((5, 5), np.uint8)
    sea[2, :3] = 0
    sea[1, 3:] = 0  # the wall steps up one row: only a diagonal joins the seas through land
    with pytest.raises(ValueError, match="leak"):
        rp.assert_closed(sea)


def test_pier_on_land_starts_from_the_nearest_sea_pixel():
    land, _, _ = _headland()
    x0, y0 = _x0y0()
    inland = Point(x0 + 10_000, y0 + 20_400)  # 400 m inside the shore
    p = gpd.GeoDataFrame(
        {"pier_id": ["pier_0"], "name": [None], "road_access": [True]}, geometry=[inland], crs=32629
    )
    th = rp.travel_hours(rp.sea_raster(land), p)
    assert len(th) > 0 and np.isfinite(th["hours"]).all()
