"""Cell-averaging CFAR on linear power."""

import numpy as np
import pandas as pd


def estimate_enl(img, patch) -> float:  # stub, issue #3
    return 4.4


def background(img, outer=41, guard=11):  # stub, issue #3
    return np.full_like(img, np.nan)


def alpha(L, p_fa=1e-7) -> float:  # stub, issue #3
    return np.inf


def flag(img, mu_b, alpha):  # stub, issue #3
    return np.zeros(img.shape, bool)


def clusters(mask, img, mu_b) -> pd.DataFrame:  # stub, issue #4
    return pd.DataFrame(columns=["x_m", "y_m", "n_px", "peak_ratio_db"])


def merge_pols(vv, vh, gate_m=30) -> pd.DataFrame:  # stub, issue #4
    return pd.DataFrame(columns=["x_m", "y_m", "pol_agree", "n_px", "peak_ratio_vv_db", "peak_ratio_vh_db"])


def size_class(n_px):  # stub, issue #4
    return "small"
