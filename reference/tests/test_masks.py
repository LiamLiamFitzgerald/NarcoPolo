"""reference/masks (#35): the land mask with its coastal buffer, the static-object mask from repeated bright spots, and
static_frac. The static mask runs on the simulator's own radar chips (raw/s1, written by `simulate`)."""

import struct
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from core import io
from core.config import load
from core.grid import FINE, _origin
from core.schemas import check_raster
from reference import masks as rm
from sim.simulate import simulate


def _read_chip(path: Path) -> tuple[np.ndarray, float, float]:
    """VV dB and the top-left corner of one simulator chip (uncompressed GeoTIFF, int16 dB x 100)."""
    b = path.read_bytes()
    (ifd,) = struct.unpack_from("<I", b, 4)
    (n,) = struct.unpack_from("<H", b, ifd)
    tags = {}
    for i in range(n):
        tag, typ, count, val = struct.unpack_from("<HHII", b, ifd + 2 + 12 * i)
        size, fmt = {3: (2, "H"), 4: (4, "I"), 12: (8, "d")}[typ]
        at = ifd + 2 + 12 * i + 8 if size * count <= 4 else val
        tags[tag] = struct.unpack_from(f"<{count}{fmt}", b, at)
    w, h = tags[256][0], tags[257][0]
    vv = np.frombuffer(b, "<i2", w * h, tags[273][0]).reshape(h, w) / 100.0
    return vv, tags[33922][3], tags[33922][4]


def _scene(vv_north_up: np.ndarray, xmin: float, ymax: float) -> rm.Scene:
    """A north-up chip placed on the mask grid (row 0 = south, like the masks)."""
    x0, y0 = _origin()
    h = vv_north_up.shape[0]
    return rm.Scene(
        row0=round((ymax - h * 10 - y0) / 10), col0=round((xmin - x0) / 10), vv_db=vv_north_up[::-1]
    )


@pytest.fixture(scope="module")
def sim(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    raw = tmp_path_factory.mktemp("raw")
    mp.setenv("NARCO_DATA", str(tmp_path_factory.mktemp("data")))
    mp.setenv("NARCO_RAW", str(raw))
    simulate(load(io.CONFIG_PATH)[0], 20261127)
    # 15 passes (of ~90, ~1 s each) keep the test quick and are enough for a 60% rule; names are hashes, so this is a mixed set
    chips = [_read_chip(p) for p in sorted((raw / "s1").glob("*.tif"))[:15]]
    site = io.read_stage("fuse/sites").iloc[0]
    mp.undo()
    return chips, (float(site["x_m"]), float(site["y_m"]))


def _land() -> BaseGeometry:
    x0, y0 = _origin()
    return box(x0 + 100_000, y0 + 40_000, x0 + 120_000, y0 + 60_000)


def test_land_mask_buffers_300_m_and_fits_the_contract():
    land = rm.land_mask_10m(_land())
    check_raster("reference/land_mask_10m", land, pixel_m=10, origin=_origin())
    r, c = 4_500, 10_000 - 29  # 290 m west of the land's west edge
    assert land[r, c] == 1 and land[r, c - 2] == 0  # 290 m is buffered, 310 m is not
    assert land[5_000, 11_000] == 1  # inside the land
    assert land[:3_000].sum() == 0  # open sea far to the south


def test_planted_drop_site_never_masked_and_a_fixed_object_is(sim):
    chips, (sx, sy) = sim
    assert len(chips) == 15
    x0, y0 = _origin()
    scenes = []
    fixed = None
    for vv, xmin, ymax in chips:
        s = _scene(vv.copy(), xmin, ymax)
        if fixed is None:  # a buoy 1 km east of the site, bright in every pass that covers it
            fixed = (int((sy - y0) // 10) - s.row0, int((sx + 1000 - x0) // 10) - s.col0)
        if 0 <= fixed[0] < s.vv_db.shape[0] and 0 <= fixed[1] < s.vv_db.shape[1]:
            s.vv_db[fixed] = np.median(s.vv_db) + 20
        scenes.append(s)
    land = np.zeros(rm._grid_shape(), np.uint8)
    static = rm.static_mask_10m(scenes, land)
    check_raster("reference/static_mask_10m", static, pixel_m=10, origin=_origin())
    rs, cs = int((sy - y0) // 10), int((sx - x0) // 10)
    assert (
        static[rs - 30 : rs + 30, cs - 30 : cs + 30].sum() == 0
    )  # the site and its pick-ups, 300 m around
    assert static[rs, int((sx + 1000 - x0) // 10)] == 1  # the buoy
    # grown by 100 m: masked 90 m away, not 160 m away (the 50 m bin adds up to 50 m)
    bc = int((sx + 1000 - x0) // 10)
    assert static[rs, bc + 9] == 1 and static[rs, bc + 16] == 0


def test_bright_in_too_few_passes_is_not_static():
    vv = np.full((100, 100), -20.0)
    scenes = []
    for k in range(10):
        a = vv.copy()
        if k < 5:  # bright in 50% of passes, under the 60% rule
            a[50, 50] = -5
        scenes.append(rm.Scene(1000, 1000, a))
    out = rm.static_mask_10m(scenes, np.zeros(rm._grid_shape(), np.uint8))
    assert out.sum() == 0
    scenes[5].vv_db[50, 50] = -5  # now 6 of 10
    out = rm.static_mask_10m(scenes, np.zeros(rm._grid_shape(), np.uint8))
    assert out[1050, 1050] == 1


def test_land_is_never_static():
    vv = np.full((100, 100), -20.0)
    vv[50, 50] = -5
    land = np.zeros(rm._grid_shape(), np.uint8)
    land[1040:1060, 1040:1060] = 1
    out = rm.static_mask_10m([rm.Scene(1000, 1000, vv)] * 3, land)
    assert out.sum() == 0


def test_static_frac_is_the_masked_share_of_each_cell():
    mask = np.zeros(rm._grid_shape(), np.uint8)
    mask[200:300, 400:600] = 1  # half of cell (2, 1)
    x0, y0 = _origin()
    cells = gpd.GeoDataFrame(
        {"cell_id": ["2000_2_1", "2000_0_0"]},
        geometry=[
            box(x0 + 2 * FINE, y0 + FINE, x0 + 3 * FINE, y0 + 2 * FINE),
            box(x0, y0, x0 + FINE, y0 + FINE),
        ],
        crs=32629,
    )
    f = rm.static_frac(cells, mask)
    assert list(f) == [pytest.approx(0.5), 0.0]
