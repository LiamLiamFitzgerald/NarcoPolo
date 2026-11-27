"""Cell-averaging CFAR on linear power."""

import numpy as np
import pandas as pd
from scipy import ndimage, stats

from detect._standin import CFG


def estimate_enl(img: np.ndarray, patch: tuple[slice, slice]) -> float:
    """Equivalent number of looks, mean^2 / variance, on a patch of open calm sea."""
    v = img[patch]
    v = v[np.isfinite(v)]
    return float(v.mean() ** 2 / v.var())


def _box_sum(a: np.ndarray, size: int) -> np.ndarray:
    return ndimage.uniform_filter(a, size=size, mode="constant", cval=0.0) * size**2


def background(img: np.ndarray, outer: int = CFG["cfar_outer"], guard: int = CFG["cfar_guard"]) -> np.ndarray:
    """Mean of the ring between the outer window and the guard window, skipping NaN pixels.

    Linear power only. Masked (NaN) pixels count neither in the sum nor in the pixel count,
    so the coast does not drag the background down. Pixels with an empty ring get NaN.
    """
    valid = np.isfinite(img)
    vals = np.where(valid, img, 0.0)
    s = _box_sum(vals, outer) - _box_sum(vals, guard)
    n = _box_sum(valid.astype(np.float64), outer) - _box_sum(valid.astype(np.float64), guard)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0.5, s / n, np.nan)


def alpha(L: float, p_fa: float = CFG["p_fa"]) -> float:
    """Threshold multiplier from the gamma speckle tail: P(I / mean > alpha) = p_fa."""
    return float(stats.gamma.isf(p_fa, a=L, scale=1 / L))


def flag(img: np.ndarray, mu_b: np.ndarray, alpha: float) -> np.ndarray:
    """Pixels brighter than alpha times their background. NaN pixels are never flagged."""
    with np.errstate(invalid="ignore"):
        return img > alpha * mu_b


def clusters(mask, img, mu_b) -> pd.DataFrame:  # stub, issue #4
    return pd.DataFrame(columns=["x_m", "y_m", "n_px", "peak_ratio_db"])


def merge_pols(vv, vh, gate_m=30) -> pd.DataFrame:  # stub, issue #4
    return pd.DataFrame(columns=["x_m", "y_m", "pol_agree", "n_px", "peak_ratio_vv_db", "peak_ratio_vh_db"])


def size_class(n_px):  # stub, issue #4
    return "small"
