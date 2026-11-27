import shutil

import numpy as np
import pytest

from core import io
from core.config import load
from sim.simulate import simulate
from validate.backtest import COLUMNS, backtest

forecast = pytest.importorskip("forecast")
if not hasattr(forecast, "forecast_all"):
    pytest.skip("P5's forecast_all is not on integration yet", allow_module_level=True)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("bt")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    mp.setenv("NARCO_RAW", str(tmp / "raw"))
    cfg = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    mp.setattr(io, "CONFIG_PATH", cfg)
    simulate(load(cfg)[0], 20261127)
    yield
    mp.undo()


@pytest.mark.parametrize("event_type", ["slowdown", "dark_small"])
def test_one_row_per_model_with_finite_skill_range(world, event_type):
    t = backtest(event_type)
    assert list(t.columns) == COLUMNS and set(t["model"]) == {"ewma", "glm"}
    assert (t["event_type"] == event_type).all()
    assert np.isfinite(
        t[["mean", "min", "max"]].to_numpy()
    ).all()  # infinite deviance (zero forecasts, #58) fails here
    assert ((t["min"] <= t["mean"]) & (t["mean"] <= t["max"])).all()


def test_skill_is_a_real_comparison_not_a_broken_one(world):
    # constant per-cell rates make the flat baseline the true model, so skill > 0 is a real-data criterion only
    skill = backtest("slowdown")["mean"]
    assert (skill < 1).all()  # exactly 1 means the flat baseline's deviance was infinite
