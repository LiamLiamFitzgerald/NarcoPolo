"""Square cells in EPSG:32629. Fine cells (2 km) nest exactly in coarse cells (10 km) because x0, y0 are multiples of 10 km."""

from functools import cache
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike, NDArray

from core.config import load

FINE, COARSE = 2000, 10000


@cache
def _origin() -> tuple[float, float]:
    cfg, _ = load(Path(__file__).resolve().parent.parent / "config.yaml")
    return float(cfg["x0"]), float(cfg["y0"])


def _check(s: int) -> int:
    if s not in (FINE, COARSE):
        raise ValueError(f"cell size must be {FINE} or {COARSE}, got {s}")
    return s


def cell_index(
    x_m: ArrayLike, y_m: ArrayLike, s: int
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    x0, y0 = _origin()
    ix = np.floor((np.asarray(x_m, float) - x0) / _check(s)).astype(np.int64)
    iy = np.floor((np.asarray(y_m, float) - y0) / s).astype(np.int64)
    return ix, iy


def cell_id(ix: int, iy: int, s: int) -> str:
    return f"{_check(s)}_{ix}_{iy}"


def _parse(cid: str) -> tuple[int, int, int]:
    s, ix, iy = (int(p) for p in cid.split("_"))
    return _check(s), ix, iy


def parent(cid: str) -> str:
    s, ix, iy = _parse(cid)
    if s != FINE:
        raise ValueError(f"only a {FINE} m cell has a parent, got {cid}")
    return cell_id(ix // 5, iy // 5, COARSE)


def centroid(cid: str) -> tuple[float, float]:
    s, ix, iy = _parse(cid)
    x0, y0 = _origin()
    return x0 + (ix + 0.5) * s, y0 + (iy + 0.5) * s


def neighbours(cell_ids: list[str], radius_m: float) -> dict[str, list[str]]:
    """For each cell, the other cells in `cell_ids` whose centroid is within radius_m (itself excluded)."""
    xy = np.array([centroid(c) for c in cell_ids])
    d = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1])
    return {
        c: [cell_ids[j] for j in np.flatnonzero(d[i] <= radius_m) if j != i]
        for i, c in enumerate(cell_ids)
    }
