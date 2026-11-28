"""A stack of radar passes over one patch of sea for the fixed-target suppression test (#334).

Fixed bright targets (rocks, buoys, fish farms) sit in the same pixels on every pass; small boats of known length
(sim.pickup_length_m) sit at new random pixels on each pass; clutter is fresh gamma speckle every pass. Every target
is added in linear power over a sea mean of 1, never in dB. Own code only: nothing from detect (P1 warning).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.config import Config
from sim.scenes import ENL

SIGMA_PX = 1.0  # same spot shape as validate's injection test (spec: Gaussian, sigma 1 px)
_EDGE = 20  # px kept clear of the edge so every spot and most of its CFAR ring are inside the patch


@dataclass(frozen=True)
class Stack:
    images: np.ndarray  # passes x rows x cols, linear power, sea mean 1
    fixed: np.ndarray  # n_fixed x 2 (row, col), the same on every pass
    boats: pd.DataFrame  # pass, row, col, length_m, peak_db


def _spot(img: np.ndarray, r: int, c: int, db: float) -> None:
    k = int(np.ceil(4 * SIGMA_PX))
    rr, cc = np.mgrid[r - k : r + k + 1, c - k : c + k + 1]
    img[rr, cc] += (10 ** (db / 10) - 1) * np.exp(
        -((rr - r) ** 2 + (cc - c) ** 2) / (2 * SIGMA_PX**2)
    )


def fixed_target_stack(config: Config, seed: int) -> Stack:
    s, f = config["sim"], config["sim"]["fixed_targets"]
    rng = np.random.default_rng(seed + s["seed_offsets"]["fixed_targets"])
    n, k = int(f["size_px"]), int(f["n_passes"])
    fixed = rng.integers(_EDGE, n - _EDGE, (int(f["n_fixed"]), 2))
    lo, hi = s["pickup_length_m"]
    db_lo, db_hi = f["boat_db"]
    images, rows = np.empty((k, n, n)), []
    for p in range(k):
        img = rng.gamma(ENL, 1 / ENL, (n, n))
        for r, c in fixed:
            _spot(img, int(r), int(c), float(f["fixed_db"]))
        at = rng.integers(_EDGE, n - _EDGE, (int(f["boats_per_pass"]), 2))
        length = rng.uniform(lo, hi, len(at))
        peak = db_lo + (length - lo) / (hi - lo) * (
            db_hi - db_lo
        )  # brighter with length, linear in dB
        for (r, c), db in zip(at, peak, strict=True):
            _spot(img, int(r), int(c), float(db))
        images[p] = img
        rows.append(
            pd.DataFrame(
                {"pass": p, "row": at[:, 0], "col": at[:, 1], "length_m": length, "peak_db": peak}
            )
        )
    return Stack(images, fixed, pd.concat(rows, ignore_index=True))
