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


def test_best_model_beats_flat_on_slowdowns(world):
    # the simulator plants a lane and an anchorage, so a model with covariates must beat each cell's flat rate
    skill = backtest("slowdown")["mean"]
    assert (
        0 < skill.max() < 1
    )  # exactly 1 means the flat baseline's deviance was infinite, not a perfect model
