import numpy as np

from core.crs import to_utm, to_wgs84

HAULBOWLINE = (-8.30, 51.845)  # lon, lat; approximate


def test_haulbowline_round_trips_within_1m():
    x, y = to_utm(*HAULBOWLINE)
    lon, lat = to_wgs84(x, y)
    xb, yb = to_utm(lon, lat)
    assert abs(xb - x) < 1 and abs(yb - y) < 1


def test_lon_is_x_not_lat():
    # UTM 29N: central meridian -9, so lon -8.3 is ~50 km east of 500000; y is ~5.74e6 m north.
    x, y = to_utm(*HAULBOWLINE)
    assert 540_000 < x < 560_000 and 5_700_000 < y < 5_800_000


def test_arrays():
    x, y = to_utm(np.array([-8.3, -9.0]), np.array([51.8, 51.5]))
    assert x.shape == y.shape == (2,)
    assert abs(x[1] - 500_000) < 1
