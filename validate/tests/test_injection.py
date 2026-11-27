import importlib
import shutil
import types

import numpy as np
import pytest

from core import io
from core.config import load
from sim.simulate import simulate
from validate.injection import COLUMNS, _add_spot, injection_test


@pytest.mark.parametrize("db", [3.0, 10.0, 15.0])
def test_spot_is_added_in_linear_power(db):
    img = np.full((21, 21), 0.01)
    _add_spot(img, 10, 10, db, 0.01)
    assert img[10, 10] / 0.01 == pytest.approx(
        10 ** (db / 10)
    )  # dB arithmetic would give 0.01 + db
    assert img.argmax() == 10 * 21 + 10
    # sigma = 1 px: a neighbour gets exp(-1/2) of the added power
    assert (img[10, 11] - 0.01) / (img[10, 10] - 0.01) == pytest.approx(np.exp(-0.5))


def test_empty_frame_without_p4_detector(monkeypatch):
    real = importlib.import_module
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: types.ModuleType(name) if name.startswith("detect") else real(name),
    )
    t = injection_test(["x"], [3.0], 2, 1)
    assert list(t.columns) == COLUMNS and t.empty


def _has_run_pass() -> bool:
    try:
        return hasattr(importlib.import_module("detect.pipeline"), "run_pass")
    except ImportError:
        return False


@pytest.fixture(scope="module")
def pass_ids(tmp_path_factory):
    if not _has_run_pass():
        pytest.skip("P4's detect.pipeline.run_pass is not on integration yet")
    tmp = tmp_path_factory.mktemp("inj")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    mp.setenv("NARCO_RAW", str(tmp / "raw"))
    cfg = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    mp.setattr(io, "CONFIG_PATH", cfg)
    simulate(load(cfg)[0], 20261127)
    yield sorted(p.stem for p in (tmp / "raw" / "s1").glob("*.json"))[:3]
    mp.undo()


def test_recall_rises_with_brightness_and_is_deterministic(pass_ids):
    levels = [3.0, 6.0, 10.0, 15.0]
    t = injection_test(pass_ids, levels, 10, 7)
    assert list(t.columns) == COLUMNS and t["brightness_db"].tolist() == levels
    assert t["recall"].is_monotonic_increasing
    assert t["recall"].iloc[-1] > t["recall"].iloc[0]
    assert (t["false_alarms_per_km2"] >= 0).all()
    print(t.to_string())
    assert injection_test(pass_ids, levels, 10, 7).equals(t)
