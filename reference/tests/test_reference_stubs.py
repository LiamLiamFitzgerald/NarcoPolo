import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

import reference
from core import io
from core.config import load
from core.grid import FINE, _origin
from core.schemas import check
from reference import cells as rc
from reference import masks, piers
from sim.simulate import simulate


@pytest.fixture(scope="module")
def sim(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp_path_factory.mktemp("data")))
    simulate(load(io.CONFIG_PATH)[0], 20261127)
    yield
    mp.undo()


def test_run_on_simulator_keeps_reference_files_valid(sim):
    reference.run()
    for name in ("reference/cells", "reference/piers", "reference/travel_hours"):
        assert len(io.read_stage(name)) > 0


def test_build_cells_keeps_only_sea_cells_on_the_core_grid():
    x0, y0 = _origin()
    region = box(x0, y0, x0 + 3 * FINE, y0 + 2 * FINE)
    land = box(x0, y0 + FINE, x0 + FINE, y0 + 2 * FINE)  # top-left cell is land
    out = rc.build_cells(region, land)
    assert sorted(out["cell_id"]) == ["2000_0_0", "2000_1_0", "2000_1_1", "2000_2_0", "2000_2_1"]
    assert (out["sea_frac"] == 1).all()


def test_fine_and_coarse_layers_pass_the_cells_schema(sim):
    fine = gpd.GeoDataFrame(io.read_stage("reference/cells").query("level == 2000"))
    harbours = gpd.GeoDataFrame(geometry=fine.centroid.iloc[:1], crs=32629)
    port = rc.port_zones(fine, harbours)
    anch = rc.anchorages(fine, rc.regrid_presence(pd.DataFrame()))
    layered = fine.assign(
        inshore_frac=rc.inshore_frac(fine, gpd.GeoDataFrame(), box(0, 0, 1, 1)),
        lane=rc.lanes(fine, pd.DataFrame()),
        anchorage=anch,
        port_zone=port,
        exclusion=rc.exclusion(port, anch),
        static_frac=masks.static_frac(fine, np.zeros((0, 0), np.uint8)),
    )
    assert port.iloc[0] and not port.all()
    assert layered["inshore_frac"].isna().all()  # unknown, never 0
    both = pd.concat([layered, rc.to_coarse(layered)], ignore_index=True)
    check("reference/cells", gpd.GeoDataFrame(both, crs=32629))
    assert both["cell_id"].str.startswith("10000_").any()


def test_masks_mask_nothing_yet():
    land = masks.land_mask_10m(box(0, 0, 1, 1))
    assert masks.static_mask_10m([], land).shape == land.shape


def test_sea_raster_and_travel_hours_are_schema_valid():
    x0, y0 = _origin()
    land = box(x0, y0, x0 + 1000, y0 + 1000)
    sea = piers.sea_raster(land)
    assert sea[0, 0] == 0 and sea[10, 10] == 1
    piers.assert_closed(sea)
    osm = gpd.GeoDataFrame(
        {"name": ["A", None]}, geometry=[Point(x0 + 5000, y0 + 5000), Point(x0, y0)], crs=32629
    )
    p = piers.piers(osm, gpd.GeoDataFrame())
    check("reference/piers", p)
    th = check("reference/travel_hours", piers.travel_hours(sea, p))
    one = th[(th["cell_id"] == "2000_2_2") & (th["pier_id"] == "pier_0")]["hours"].item()
    assert one == pytest.approx(0.0)  # pier sits on that cell's centre
