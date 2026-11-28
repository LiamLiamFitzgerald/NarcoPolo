"""coverage (#37) against the simulator's own raw files: raw/s1/*.json footprints and raw/era5.nc."""

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

import coverage as cv
from core import io
from core.config import load
from core.grid import FINE, _origin
from core.schemas import check
from sim.simulate import simulate


@pytest.fixture(scope="module")
def sim(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    raw = tmp_path_factory.mktemp("raw")
    mp.setenv("NARCO_DATA", str(tmp_path_factory.mktemp("data")))
    mp.setenv("NARCO_RAW", str(raw))
    simulate(load(io.CONFIG_PATH)[0], 20261127)
    cells = gpd.GeoDataFrame(io.read_stage("reference/cells"), crs=32629)
    truth = io.read_stage("coverage/exposure")
    era5 = cv._read_era5(raw / "era5.nc")
    passes = cv._read_passes(raw / "s1")
    mp.undo()
    return cells, truth, era5, passes


def test_reads_every_scene_pass(sim):
    _, truth, _, passes = sim
    assert len(passes) > 20 and passes["downloaded"].all()
    assert set(passes["pass_id"]) <= set(truth["pass_id"])


def test_recovers_the_simulated_weather_and_coverage(sim):
    cells, truth, era5, passes = sim
    out = cv.build_exposure(passes, cells, era5)
    check("coverage/exposure", out)
    m = out.merge(truth, on=["cell_id", "pass_id"], suffixes=("", "_sim"))
    fine = cells[cells["level"] == 2000].set_index("cell_id")["sea_frac"]
    assert len(m) == len(out)
    assert np.allclose(m["wind_ms"], m["wind_ms_sim"], atol=1e-4)  # ERA5 stored as float32
    assert np.allclose(
        m["hs_m"], m["hs_m_sim"], atol=1e-4
    )  # shore cells take the nearest wave point (A8)
    # the simulator's covered_frac ignores land; the spec's counts only sea: they differ by sea_frac
    # (footprints are stored to 0.1 m in the scene JSON, so edge cells differ by ~1e-5)
    assert np.allclose(m["covered_frac"], m["covered_frac_sim"] * m["cell_id"].map(fine), atol=1e-4)


def test_a_known_pass_covers_its_footprint_area_within_2_percent(sim):
    cells, _, _, passes = sim
    fine = cells[cells["level"] == 2000]
    p = passes.iloc[0]
    cov = cv.covered_frac(p.footprint, fine)
    sea = fine.geometry.union_all()  # the simulator's cells span exactly its sea band
    shore = fine[fine["sea_frac"] < 1]  # the shore row is only part sea, along its southern side
    top = shore.geometry.bounds["miny"].min() + shore["sea_frac"].iloc[0] * FINE
    sea = sea.intersection(box(*sea.bounds[:3], top))
    want = p.footprint.intersection(sea).area
    assert (cov * fine.area).sum() == pytest.approx(want, rel=0.02)


def test_a_rough_pass_gives_zero_small_boat_exposure_everywhere(sim):
    cells, _, era5, passes = sim
    out = cv.build_exposure(passes, cells, era5)
    rough = out.groupby("pass_id")["wind_ms"].min() >= 6
    assert rough.any(), "the simulator should have at least one rough pass"
    assert (out[out["pass_id"].isin(rough[rough].index)]["exposure_small"] == 0).all()
    calm = out[out["calm"]]
    assert (calm["exposure_small"] == calm["covered_frac"]).all()


def test_a_pass_not_downloaded_is_unobserved_even_when_calm(sim):
    cells, _, era5, passes = sim
    p = passes.copy()
    p["downloaded"] = False
    out = cv.build_exposure(p, cells, era5)
    assert out["calm"].any() and (out["exposure_small"] == 0).all()


def test_post_storm_needs_24_stormy_hours_in_the_last_72():
    cells = gpd.GeoDataFrame(
        geometry=[box(*_origin(), _origin()[0] + FINE, _origin()[1] + FINE)], crs=32629
    )
    t = np.datetime64("2026-08-01T00:00", "ns") + np.arange(100) * np.timedelta64(1, "h")
    from core.crs import to_wgs84

    c = cells.centroid
    lon, lat = to_wgs84(c.x.iloc[0], c.y.iloc[0])
    swh = np.full((100, 1, 1), 1.0)
    era5 = {
        "time": t,
        "lat": np.array([float(lat)]),
        "lon": np.array([float(lon)]),
        "u10": np.zeros((100, 1, 1)),
        "v10": np.zeros((100, 1, 1)),
        "swh": swh,
    }
    when = pd.Timestamp("2026-08-04T04:00", tz="UTC")  # hour 76
    swh[20:43] = 3.0  # 23 stormy hours inside the window
    assert not cv.post_storm(era5, cells, when).iloc[0]
    swh[43] = 3.0  # 24
    assert cv.post_storm(era5, cells, when).iloc[0]
    swh[:] = 1.0
    swh[0:30] = (
        3.0  # 30 stormy hours, but a pass at hour 99 looks back over hours 27-98: only 3 of them
    )
    assert not cv.post_storm(era5, cells, pd.Timestamp("2026-08-05T03:00", tz="UTC")).iloc[0]
