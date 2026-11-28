"""reference.run and coverage.run on raw/ files: the real-data path, run on the simulator's copies of P2's files.
Known answer: rebuilt from raw/, the cells, sea_frac, inshore_frac and exposure equal what the simulator planted."""

import functools
import json
import shutil

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

import coverage
import reference
from core import io
from core.config import load
from core.grid import FINE
from reference import _real
from sim.simulate import simulate

pytestmark = pytest.mark.slow  # shared setup >= 12 s (28 Nov); run with `pytest -m slow`


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Simulate, keep the simulator's own files, then rebuild reference and coverage from raw/ as if real."""
    tmp = tmp_path_factory.mktemp("p3real")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    mp.setenv("NARCO_RAW", str(tmp / "raw"))
    cfg = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    mp.setattr(io, "CONFIG_PATH", cfg)
    simulate(load(cfg)[0], 20261127)
    planted = {
        n: io.read_stage(n)
        for n in (
            "reference/cells",
            "reference/land",
            "reference/travel_hours",
            "coverage/exposure",
        )
    }
    fine = planted["reference/cells"].query("level == 2000")
    x0, y0, x1, y1 = gpd.GeoSeries(fine.geometry).total_bounds
    # the simulator\'s coastline only crosses its own box (room above the shore row, as in test_land)
    mp.setattr(_real, "region", lambda: box(x0, y0, x1, y1 + FINE))
    mp.setattr(
        _real, "build", functools.partial(_real.build, max_scenes=10)
    )  # static mask: 10 scenes is enough here
    for mod in (reference, coverage):
        mp.setattr(mod, "_raw_is_real", lambda: True)
    reference.run()
    coverage.run()
    yield planted
    mp.undo()


def test_sim_manifest_is_not_real_and_an_unmarked_one_is(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_RAW", str(tmp_path))
    assert not reference._raw_is_real()  # no manifest
    f = {"request": {"bbox": [0, 0, 1, 1]}, "sha256": "x"}
    for marker, real in ((None, True), ("simulated", False), ("stub", False)):
        req = dict(f["request"], **({marker: True} if marker else {}))
        (tmp_path / "manifest.json").write_text(
            json.dumps({"files": {"a.tif": {**f, "request": req}}})
        )
        assert reference._raw_is_real() is real and coverage._raw_is_real() is real


def test_rebuilt_cells_equal_the_planted_ones(built):
    p, b = built["reference/cells"], io.read_stage("reference/cells")
    assert io.read_provenance("reference/cells") == "real"
    for lvl in (2000, 10000):
        assert set(b.loc[b["level"] == lvl, "cell_id"]) == set(p.loc[p["level"] == lvl, "cell_id"])
    m = p.query("level == 2000").merge(
        b.query("level == 2000"), on="cell_id", suffixes=("_p", "_b")
    )
    assert np.allclose(m["sea_frac_p"], m["sea_frac_b"])
    assert np.allclose(m["inshore_frac_p"], m["inshore_frac_b"], equal_nan=True)


def test_rebuilt_land_matches_the_planted_land(built):
    """P7's basemap layer (#105): the land closed from raw/coastline.gpkg covers the simulator's own land strip."""
    assert io.read_provenance("reference/land") == "real"
    b = gpd.GeoSeries(io.read_stage("reference/land").geometry, crs=32629).union_all()
    p = gpd.GeoSeries(built["reference/land"].geometry, crs=32629).union_all()
    assert b.area > 0
    # the rebuilt land reaches the test region's edge (a cell above the grid), the simulator's stops at the grid's
    # top: inside the box both cover, they must agree
    both = b.envelope.intersection(p.envelope)
    assert b.intersection(both).symmetric_difference(p.intersection(both)).area < 1e-3 * both.area


def test_rebuilt_travel_times_follow_the_planted_ones(built):
    p, b = built["reference/travel_hours"], io.read_stage("reference/travel_hours")
    m = p.merge(b, on=["cell_id", "pier_id"], suffixes=("_p", "_b"))
    assert len(m) >= 0.5 * len(p)
    assert (
        abs((m["hours_b"] / m["hours_p"]).median() - 1) < 0.1
    )  # same sea, a 250 m raster path vs straight line


def test_rasters_are_written_on_the_grid(built):
    import rasterio

    for name in io.RASTERS:
        with rasterio.open(io.raster_path(name)) as src:
            assert src.crs.to_epsg() == 32629 and src.read(1).max() <= 1


def test_rebuilt_exposure_matches_the_planted_passes(built):
    p, b = built["coverage/exposure"], io.read_stage("coverage/exposure")
    assert io.read_provenance("coverage/exposure") == "real"
    key = ["cell_id", "pass_id"]
    # the simulator writes raw/s1 metadata only for passes that reach its chip, so only those can be rebuilt
    assert set(b["pass_id"]) <= set(p["pass_id"]) and b["pass_id"].nunique() > 10
    m = p.merge(b, on=key, suffixes=("_p", "_b"))
    assert len(m) == len(b)
    assert np.allclose(m["wind_ms_p"], m["wind_ms_b"], atol=1e-4) and np.allclose(
        m["hs_m_p"], m["hs_m_b"], atol=1e-4
    )
    c = load(io.CONFIG_PATH)[0][
        "coverage"
    ]  # P3's calm rule; the simulator uses its own rough_wind_ms
    assert (
        m["calm_b"] == (m["wind_ms_b"] < c["calm_wind_ms"]) & (m["hs_m_b"] < c["calm_hs_m"])
    ).all()
    sea = io.read_stage("reference/cells").set_index("cell_id")["sea_frac"]
    # the simulator\'s covered_frac ignores land; P3\'s counts sea only (PR #122)
    assert np.allclose(m["covered_frac_b"], m["covered_frac_p"] * m["cell_id"].map(sea), atol=1e-3)
    assert pd.api.types.is_bool_dtype(b["post_storm"])
