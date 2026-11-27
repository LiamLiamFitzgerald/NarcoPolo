"""One coordinate system for the whole project: EPSG:32629 (UTM 29N), metres."""

import numpy as np
from numpy.typing import ArrayLike, NDArray
from pyproj import Transformer

# always_xy=True is mandatory: without it pyproj may swap lat and lon and every distance is wrong.
_TO_UTM = Transformer.from_crs(4326, 32629, always_xy=True)
_TO_WGS84 = Transformer.from_crs(32629, 4326, always_xy=True)


def to_utm(lon: ArrayLike, lat: ArrayLike) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    x, y = _TO_UTM.transform(np.asarray(lon, float), np.asarray(lat, float))
    return np.asarray(x), np.asarray(y)


def to_wgs84(x_m: ArrayLike, y_m: ArrayLike) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Inverse of to_utm; for export only."""
    lon, lat = _TO_WGS84.transform(np.asarray(x_m, float), np.asarray(y_m, float))
    return np.asarray(lon), np.asarray(lat)
