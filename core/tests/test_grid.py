import pytest

from core import grid
from core.crs import to_utm
from core.grid import cell_id, cell_index, centroid, neighbours, parent


def test_25_children_share_one_parent():
    kids = [cell_id(10 + i, 20 + j, 2000) for i in range(5) for j in range(5)]
    assert {parent(k) for k in kids} == {cell_id(2, 4, 10000)}
    assert parent(cell_id(15, 20, 2000)) != parent(kids[0])


def test_parent_floors_negative_indices():
    assert parent(cell_id(-1, -5, 2000)) == cell_id(-1, -1, 10000)


def test_index_centroid_roundtrip_and_origin():
    x0, y0 = grid._origin()
    x, y = x0 + 4_999.0, y0 + 2_000.0
    ix, iy = cell_index(x, y, 2000)
    assert (ix, iy) == (2, 1)
    cx, cy = centroid(cell_id(int(ix), int(iy), 2000))
    assert (cx, cy) == (x0 + 5_000.0, y0 + 3_000.0)
    assert abs(cx - x) <= 1_000 and abs(cy - y) <= 1_000


def test_real_point_inside_region_has_nonnegative_index():
    ix, iy = cell_index(*to_utm(-8.3, 51.845), 10000)
    assert ix >= 0 and iy >= 0


def test_arrays():
    ix, _ = cell_index(
        [grid._origin()[0], grid._origin()[0] + 2_000], [grid._origin()[1]] * 2, 2000
    )
    assert list(ix) == [0, 1]


def test_bad_size_and_bad_parent():
    with pytest.raises(ValueError):
        cell_index(0, 0, 500)
    with pytest.raises(ValueError):
        parent(cell_id(1, 1, 10000))


def test_neighbours_by_centroid_distance():
    a, b, c = cell_id(0, 0, 2000), cell_id(1, 0, 2000), cell_id(2, 0, 2000)
    n = neighbours([a, b, c], 2_000)
    assert n == {a: [b], b: [a, c], c: [b]}
    assert neighbours([a, b], 1_999) == {a: [], b: []}
