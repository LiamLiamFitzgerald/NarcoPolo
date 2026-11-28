"""10 m land and static-object masks on the fixed radar grid, and static_frac per cell (docs/specs/P3.md).

The grid is the one fixed region grid of shared.md issue 5: EPSG:32629, 10 m, origin (x0, y0), out to region_bbox's
far corner. Rows run south to north like sea_raster: pixel (r, c) has centre (x0 + (c + .5) 10, y0 + (r + .5) 10).
A north-up GeoTIFF is flipped once, when it is read or written. Thresholds are keyword arguments with the spec's
defaults until P3's config keys land (#85)."""

from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import NamedTuple

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from numpy.typing import NDArray
from scipy import ndimage
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from core.config import load
from core.crs import to_utm
from core.grid import FINE, _origin

PX = 10  # m per pixel
_BLOCK = 256  # pixels per side when rasterising: whole blocks inside or outside land skip the per-pixel test
_MEDIAN_ROWS = (
    64  # bin rows per median batch: ~64 x 500 bins x 1681 px x 4 B = 215 MB on a full scene
)


class Scene(NamedTuple):
    """One pass's VV sigma0 in dB on the mask grid: rows row0.., columns col0.., NaN where the pass did not look."""

    row0: int
    col0: int
    vv_db: NDArray[np.floating]


@cache
def _grid_shape() -> tuple[int, int]:
    """(rows, cols) of the fixed 10 m grid: from (x0, y0) to region_bbox's far corner in UTM."""
    cfg, _ = load(Path(__file__).resolve().parent.parent / "config.yaml")
    b = cfg["region_bbox"]
    x, y = to_utm([b["lon_min"], b["lon_max"]] * 2, [b["lat_min"]] * 2 + [b["lat_max"]] * 2)
    x0, y0 = _origin()
    return int(np.ceil((y.max() - y0) / PX)), int(np.ceil((x.max() - x0) / PX))


def land_mask_10m(coastline: BaseGeometry, buffer_m: float = 300) -> NDArray[np.uint8]:
    """1 = land or within buffer_m of it (where P4 does not detect), on the fixed 10 m grid."""
    rows, cols = _grid_shape()
    out = np.zeros((rows, cols), np.uint8)
    if coastline.is_empty:
        return out
    land = coastline.buffer(buffer_m)
    shapely.prepare(land)
    x0, y0 = _origin()
    for r in range(0, rows, _BLOCK):
        for c in range(0, cols, _BLOCK):
            r1, c1 = min(r + _BLOCK, rows), min(c + _BLOCK, cols)
            blk = box(x0 + c * PX, y0 + r * PX, x0 + c1 * PX, y0 + r1 * PX)
            if not land.intersects(blk):
                continue
            if land.contains(blk):
                out[r:r1, c:c1] = 1
                continue
            xx, yy = np.meshgrid(
                x0 + (np.arange(c, c1) + 0.5) * PX, y0 + (np.arange(r, r1) + 0.5) * PX
            )
            out[r:r1, c:c1] = shapely.contains_xy(land, xx, yy)
    return out


def static_mask_10m(
    scenes: Sequence[Scene],
    land_mask: NDArray[np.uint8],
    static_db: float = 10,
    share: float = 0.6,
    bin_m: float = 50,
    window_px: int = 41,
    grow_m: float = 100,
) -> NDArray[np.uint8]:
    """1 = a fixed bright object. A bin_m bin is fixed if its brightest VV pixel is at least static_db over the median
    of the surrounding window_px x window_px pixels in at least `share` of the passes that fully covered it; fixed
    bins are grown by grow_m. Built from raw radar, not P4's detections. Land pixels are never static. A drop site
    visited every few days stays under `share`, so it is not masked (spec warning)."""
    rows, cols = land_mask.shape
    k = round(bin_m / PX)
    nb_r, nb_c = -(-rows // k), -(-cols // k)
    bright = np.zeros((nb_r, nb_c), np.int32)
    covered = np.zeros((nb_r, nb_c), np.int32)
    half = window_px // 2
    for s in scenes:
        vv = np.asarray(s.vv_db, float)
        h, w = vv.shape
        land = land_mask[s.row0 : s.row0 + h, s.col0 : s.col0 + w].astype(bool)
        # whole bins only: pad the scene out to bin edges (NaN = not looked), then reduce each k x k block
        pr, pc = s.row0 % k, s.col0 % k
        H, W = -(-(h + pr) // k) * k, -(-(w + pc) // k) * k
        vv_p = np.full((H, W), np.nan)
        vv_p[pr : pr + h, pc : pc + w] = np.where(land, np.nan, vv)
        seen_p = np.zeros((H, W), bool)
        seen_p[pr : pr + h, pc : pc + w] = np.isfinite(vv)
        full = seen_p.reshape(H // k, k, W // k, k).all(axis=(1, 3))
        peak = np.nanmax(
            np.where(np.isnan(vv_p), -np.inf, vv_p).reshape(H // k, k, W // k, k), axis=(1, 3)
        )
        # median of the window_px x window_px pixels around each bin's centre (spec), NaN-aware at scene edges
        padded = np.pad(vv_p.astype(np.float32), half, constant_values=np.nan)
        win = np.lib.stride_tricks.sliding_window_view(padded, (window_px, window_px))
        centres = win[k // 2 :: k, k // 2 :: k][: H // k, : W // k]
        med = np.empty(centres.shape[:2], np.float32)
        for i in range(0, med.shape[0], _MEDIAN_ROWS):  # bounded memory on full-size scenes
            flat = centres[i : i + _MEDIAN_ROWS].reshape(-1, window_px * window_px)
            edge = np.isnan(flat).any(
                axis=1
            )  # windows touching land or the scene edge: NaN-aware median
            m = np.median(flat, axis=1)
            with np.errstate(all="ignore"):
                m[edge] = np.nanmedian(flat[edge], axis=1)
            med[i : i + _MEDIAN_ROWS] = m.reshape(-1, med.shape[1])
        any_hit = peak - med >= static_db  # NaN medians (nothing seen) compare False
        br, bc = s.row0 // k, s.col0 // k
        er, ec = min(br + H // k, nb_r), min(bc + W // k, nb_c)
        covered[br:er, bc:ec] += full[: er - br, : ec - bc]
        bright[br:er, bc:ec] += (any_hit & full)[: er - br, : ec - bc]
    fixed = (covered > 0) & (bright >= share * covered)
    out = np.zeros((rows, cols), np.uint8)
    if not fixed.any():
        return out
    px = np.kron(fixed, np.ones((k, k), bool))[:rows, :cols]
    g = round(grow_m / PX)
    rr, cc = np.nonzero(px)  # dilate only around the fixed pixels, not over the whole region
    r0, r1 = max(rr.min() - g, 0), min(rr.max() + g + 1, rows)
    c0, c1 = max(cc.min() - g, 0), min(cc.max() + g + 1, cols)
    yy, xx = np.mgrid[-g : g + 1, -g : g + 1]
    disk = xx**2 + yy**2 <= g**2
    out[r0:r1, c0:c1] = ndimage.binary_dilation(px[r0:r1, c0:c1], structure=disk)
    out[land_mask.astype(bool)] = 0
    return out


def static_frac(cells: gpd.GeoDataFrame, static_mask: NDArray[np.uint8]) -> pd.Series:
    """Share of each 2 km cell's pixels covered by the static mask (cells beyond the grid count as unmasked)."""
    n = FINE // PX
    vals = []
    for cid in cells["cell_id"]:
        _, ix, iy = (int(p) for p in str(cid).split("_"))
        blk = static_mask[iy * n : (iy + 1) * n, ix * n : (ix + 1) * n]
        vals.append(float(blk.sum()) / (n * n))
    return pd.Series(vals, index=cells.index, name="static_frac")
