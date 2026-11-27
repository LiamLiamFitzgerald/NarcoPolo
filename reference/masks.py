"""10 m land and static-object masks on the fixed radar grid, and static_frac per cell (docs/specs/P3.md).
Stubs (#22): masks mask nothing; the real ones come in #35."""

from collections.abc import Sequence

import geopandas as gpd
import numpy as np
import pandas as pd
from numpy.typing import NDArray
from shapely.geometry.base import BaseGeometry


def land_mask_10m(coastline: BaseGeometry, buffer_m: float = 300) -> NDArray[np.uint8]:
    """1 = land or within buffer_m of it, on the fixed 10 m grid (origin x0, y0)."""
    # stub: empty until P2 fixes the radar grid's extent (shared.md issue 5); #35
    return np.zeros((0, 0), np.uint8)


def static_mask_10m(
    scenes: Sequence[NDArray[np.floating]], land_mask: NDArray[np.uint8]
) -> NDArray[np.uint8]:
    """1 = a fixed bright object: 50 m bins bright over the 41 x 41 median in enough covering passes, grown."""
    return np.zeros_like(land_mask)  # stub: no fixed objects


def static_frac(cells: gpd.GeoDataFrame, static_mask: NDArray[np.uint8]) -> pd.Series:
    """Share of each cell covered by the static mask."""
    return pd.Series(0.0, index=cells.index)  # stub
