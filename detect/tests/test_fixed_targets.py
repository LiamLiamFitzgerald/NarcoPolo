"""#341: fixed-target suppression on a stack of same-orbit simulator passes written as real raw/s1 files."""

import json

import numpy as np
import pandas as pd
import pytest

from detect._common import CFG
from detect.pipeline import run_pass
from detect.scene import _earlier_median, to_linear
from detect.tests._scene import SIM_SEA_DB, _db100, make_scene

N, SHAPE = 5, (300, 300)
FIXED, BOAT = (100, 100), (200, 200)  # a rock or buoy on every pass; a boat on the newest pass only
T0 = pd.Timestamp("2026-09-01T06:30:00Z")


@pytest.fixture
def raw(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    (tmp_path / "s1").mkdir()
    for k in range(N + 1):  # p0 .. p4 earlier, p5 scored; orbit 23, 12 days apart
        s = make_scene(k, shape=SHAPE, pass_id=f"p{k}")
        bands = []
        for pol, band in (("vv", s.vv), ("vh", s.vh)):
            img, sea = to_linear(band), 10 ** (SIM_SEA_DB[pol] / 10)
            img[FIXED[0] : FIXED[0] + 2, FIXED[1] : FIXED[1] + 2] += sea * 10 ** (20 / 10)
            if k == N:
                img[BOAT] += sea * 10 ** (15 / 10)
            bands.append(_db100(img))
        tr = from_origin(s.meta["x_left"], s.meta["y_top"], 10, 10)
        with rasterio.open(tmp_path / f"s1/h{k}.tif", "w", driver="GTiff", height=SHAPE[0], width=SHAPE[1],
                           count=2, dtype="int16", transform=tr, crs="EPSG:32629") as f:  # fmt: skip
            f.write(np.stack(bands))
        meta = {k2: v for k2, v in s.meta.items() if k2 not in ("x_left", "y_top")}
        meta |= {"relative_orbit": 23, "start_time": (T0 + pd.Timedelta(days=12 * k)).isoformat()}
        (tmp_path / f"s1/h{k}.json").write_text(json.dumps(meta))
    return tmp_path


def _near(c, rc, px=3):
    return bool(len(c)) and bool((np.hypot(c["row"] - rc[0], c["col"] - rc[1]) <= px).any())


def _run(raw, pass_id, history, monkeypatch):
    monkeypatch.setitem(CFG, "fixed_target_history", history)
    z = np.zeros(SHAPE, np.uint8)
    return run_pass(pass_id, root=raw, masks=(z, z))


def test_fixed_target_divides_out_and_the_new_boat_stays(raw, monkeypatch):
    off = _run(raw, f"p{N}", None, monkeypatch)
    assert _near(off, FIXED) and _near(off, BOAT)  # baseline: the rock is a false alarm
    on = _run(raw, f"p{N}", N, monkeypatch)
    assert not _near(on, FIXED) and _near(on, BOAT)


def test_too_few_earlier_passes_falls_back_to_the_plain_image(raw, monkeypatch):
    plain = _run(raw, "p3", None, monkeypatch)
    fallback = _run(raw, "p3", N, monkeypatch)  # p3 has only 3 earlier passes
    pd.testing.assert_frame_equal(plain, fallback)


def test_median_never_uses_this_pass_or_a_later_one(raw):
    meta = json.loads((raw / "s1/h0.json").read_text()) | {
        "x_left": 500_000.0,
        "y_top": 5_700_000.0,
    }
    assert _earlier_median(meta | {"shape": SHAPE}, raw, 1) is None  # p0: only later passes exist
    other = meta | {"relative_orbit": 99, "start_time": "2027-01-01T00:00:00Z", "shape": SHAPE}
    assert _earlier_median(other, raw, 1) is None  # another orbit's passes never count
