import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

import coverage
from core import io
from core.config import load
from core.grid import FINE, _origin
from core.schemas import check
from sim.simulate import simulate


@pytest.fixture(scope="module")
def sim(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp_path_factory.mktemp("data")))
    simulate(load(io.CONFIG_PATH)[0], 20261127)
    yield
    mp.undo()


def test_run_on_simulator_keeps_exposure_valid(sim):
    coverage.run()
    assert len(io.read_stage("coverage/exposure")) > 0


def test_calm_needs_both_low_wind_and_low_waves():
    got = coverage.calm(pd.Series([3.0, 3.0, 9.0, float("nan")]), pd.Series([1.0, 2.0, 1.0, 1.0]))
    assert got.tolist() == [True, False, False, False]


def test_unknown_weather_gives_zero_small_boat_exposure(sim):
    cells = gpd.GeoDataFrame(io.read_stage("reference/cells"))
    x0, y0 = _origin()
    half = box(x0, y0, x0 + FINE / 2, y0 + FINE)  # half of cell 2000_0_0
    passes = pd.DataFrame(
        {
            "pass_id": ["p1", "p2"],
            "time_utc": pd.to_datetime(["2026-11-01T18:30Z", "2026-11-02T06:10Z"], utc=True),
            "footprint": [half, half],
            "downloaded": [True, False],
        }
    )
    out = coverage.build_exposure(passes, cells, era5=None)
    assert len(out) == 2 * (cells["level"] == 2000).sum()
    first = out[out["cell_id"] == "2000_0_0"]
    assert first["covered_frac"].tolist() == pytest.approx([0.5, 0.5])
    # rough or unknown passes are unobserved for small boats
    assert (out["exposure_small"] == 0).all()
    check("coverage/exposure", out.assign(wind_ms=0.0, hs_m=0.0))
