from typing import cast

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry

from core import io
from core.config import load
from core.grid import FINE
from reference.cells import build_cells
from reference.land import land
from sim.simulate import simulate

REGION = box(0, 0, 10_000, 10_000)


def _one(g: gpd.GeoDataFrame) -> BaseGeometry:
    return cast(BaseGeometry, g.geometry.iloc[0])


def _lines(*geoms) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"id": range(len(geoms))}, geometry=list(geoms), crs=32629)


def test_land_is_on_the_left_of_the_coastline():
    north = _one(land(_lines(LineString([(-1, 6000), (10_001, 6000)])), REGION))
    assert north.area == pytest.approx(10_000 * 4000)  # walking east, the left is north
    assert north.contains(Point(5000, 9000)) and not north.contains(Point(5000, 1000))
    south = _one(land(_lines(LineString([(10_001, 6000), (-1, 6000)])), REGION))
    assert south.area == pytest.approx(10_000 * 6000)  # reversed line: land flips side


def test_an_island_ring_drawn_counter_clockwise_is_land_inside():
    ring = LineString([(4000, 4000), (6000, 4000), (6000, 6000), (4000, 6000), (4000, 4000)])
    g = _one(land(_lines(ring), REGION))
    assert g.area == pytest.approx(2000 * 2000) and g.contains(Point(5000, 5000))


def test_a_coastline_ending_a_hair_inside_the_edge_still_cuts_the_region():
    # a lon/lat round trip leaves ends ~1e-10 m inside the region's edge; the region must still be cut
    out = land(_lines(LineString([(6e-11, 6_000), (10_000 - 6e-11, 6_000)])), REGION)
    assert _one(out).area == pytest.approx(10_000 * 4_000)


def test_no_coastline_means_no_land():
    assert _one(land(_lines(LineString([(-5, -5), (-1, -1)])), REGION)).is_empty


@pytest.mark.slow
def test_simulator_land_reproduces_the_planted_sea_fractions(tmp_path, monkeypatch):
    """Known answer: build_cells on the land from raw/coastline.gpkg gives the simulator's own sea_frac."""
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("NARCO_RAW", str(tmp_path / "raw"))
    simulate(load(io.CONFIG_PATH)[0], 1)
    planted = io.read_stage("reference/cells").query("level == 2000").set_index("cell_id")
    x0, y0, x1, y1 = gpd.GeoSeries(planted.geometry).total_bounds
    region = box(x0, y0, x1, y1 + FINE)  # room above the shore row, so the line splits the region
    coast = gpd.read_file(io.raw_root() / "coastline.gpkg")
    g = land(coast, region)
    assert g.crs is not None and g.crs.to_epsg() == 32629 and list(g.columns) == ["id", "geometry"]
    built = build_cells(region, _one(g), min_sea_frac=0.2).set_index("cell_id")
    assert set(built.index) == set(planted.index)
    assert np.allclose(built.loc[planted.index, "sea_frac"], planted["sea_frac"])
