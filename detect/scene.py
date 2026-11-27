"""Load a radar scene as linear sigma0 and mask it."""

import numpy as np


def load_scene(pass_id: str):  # stub, issue #2
    z = np.full((1, 1), np.nan)
    return z, z, {"pass_id": pass_id}


def apply_masks(img: np.ndarray, land: np.ndarray, static: np.ndarray) -> np.ndarray:  # stub, issue #2
    return img
