import json

import numpy as np
import pytest

from detect.scene import apply_masks, load_scene, to_linear
from detect.tests._scene import SIM_SEA_DB, make_scene


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
    assert (
        np.isnan(out[:, 50:80]).all() and np.isfinite(out[:, 81:]).sum() > 0
    )  # 300 m buffer = 30 px
    assert np.isnan(out[200, 300])
    assert not (out == 0).any()


def _write(tmp_path, name, bands, meta, crs="EPSG:32629", nodata=-32768):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    (tmp_path / "s1").mkdir(exist_ok=True)
    h, w = bands[0].shape
    with rasterio.open(tmp_path / "s1" / f"{name}.tif", "w", driver="GTiff", height=h, width=w, count=2,
                       dtype="int16", crs=crs, nodata=nodata,
                       transform=from_origin(500_000, 5_700_000, 10, 10)) as dst:  # fmt: skip
        dst.write(np.stack(bands))
    (tmp_path / "s1" / f"{name}.json").write_text(json.dumps(meta))


def test_load_scene_finds_hash_named_file_by_pass_id(tmp_path):
    s = make_scene(seed=3, shape=(20, 30))
    _write(tmp_path, "a1b2c3", [s.vv, s.vh], {"pass_id": "S1C_010271", "heading_deg": 350.0})
    _write(tmp_path, "d4e5f6", [s.vh, s.vv], {"pass_id": "S1A_000001"})
    vv, vh, meta = load_scene("S1C_010271", raw_dir=tmp_path)
    assert np.allclose(vv, to_linear(s.vv)) and np.allclose(vh, to_linear(s.vh))
    assert meta["x_left"] == 500_000 and meta["y_top"] == 5_700_000 and meta["heading_deg"] == 350.0
    with pytest.raises(FileNotFoundError):
        load_scene("S1B_999999", raw_dir=tmp_path)


def test_nodata_is_nan_not_a_tiny_power(tmp_path):
    s = make_scene(seed=4, shape=(20, 30))
    vv = s.vv.copy()
    vv[:, :5] = -32768  # off-swath
    _write(tmp_path, "h", [vv, s.vh], {"pass_id": "p"})
    out, _, _ = load_scene("p", raw_dir=tmp_path)
    assert np.isnan(out[:, :5]).all() and np.isfinite(out[:, 5:]).all()


def test_wrong_crs_or_all_nodata_fails_loudly(tmp_path):
    s = make_scene(seed=5, shape=(20, 30))
    _write(tmp_path, "c", [s.vv, s.vh], {"pass_id": "wrong_crs"}, crs="EPSG:4326")
    with pytest.raises(ValueError, match="EPSG:32629"):
        load_scene("wrong_crs", raw_dir=tmp_path)
    empty = np.full_like(s.vv, -32768)
    _write(tmp_path, "e", [empty, empty], {"pass_id": "empty"})
    with pytest.raises(ValueError, match="nodata"):
        load_scene("empty", raw_dir=tmp_path)
