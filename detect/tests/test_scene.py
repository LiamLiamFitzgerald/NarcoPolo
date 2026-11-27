import json

import numpy as np
import pytest

from detect._standin import SIM_SEA_DB, make_scene
from detect.scene import apply_masks, load_scene, to_linear


def test_linear_conversion_known_values():
    # -2000 = -20 dB -> 0.01; 0 dB -> 1; 1000 = +10 dB -> 10
    assert np.allclose(to_linear(np.array([-2000, 0, 1000], np.int16)), [0.01, 1.0, 10.0])


def test_sim_scene_mean_is_linear_sea_level():
    s = make_scene(seed=1)
    assert np.isclose(to_linear(s.vv).mean(), 10 ** (SIM_SEA_DB["vv"] / 10), rtol=0.01)


def test_masked_pixels_are_nan_never_zero():
    s = make_scene(seed=2, land_cols=50)
    static = np.zeros_like(s.static)
    static[200, 300] = 1
    out = apply_masks(to_linear(s.vv), s.land, static)
    assert np.isnan(out[:, :50]).all()  # land
    assert np.isnan(out[:, 50:80]).all() and np.isfinite(out[:, 81:]).sum() > 0  # 300 m buffer = 30 px
    assert np.isnan(out[200, 300])
    assert not (out == 0).any()


def test_load_scene_reads_geotiff(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    s = make_scene(seed=3, shape=(20, 30))
    (tmp_path / "s1").mkdir()
    with rasterio.open(tmp_path / "s1" / "p1.tif", "w", driver="GTiff", height=20, width=30, count=2,
                       dtype="int16", transform=from_origin(500_000, 5_700_000, 10, 10)) as dst:  # fmt: skip
        dst.write(np.stack([s.vv, s.vh]))
    (tmp_path / "s1" / "p1.json").write_text(json.dumps({"heading_deg": 350.0}))
    vv, vh, meta = load_scene("p1", raw_dir=tmp_path)
    assert np.allclose(vv, to_linear(s.vv)) and np.allclose(vh, to_linear(s.vh))
    assert meta["x_left"] == 500_000 and meta["y_top"] == 5_700_000 and meta["heading_deg"] == 350.0
