import numpy as np
import pytest

from detect._standin import SIM_META, make_scene
from detect.cfar import alpha, background, clusters, flag
from detect.ghost import azimuth_heading, ghost_offset_m, is_ghost
from detect.scene import to_linear


def test_offset_formula_and_band():
    # 0.0555 * 850 km * 1700 Hz / (2 * 7600 m/s) = 5276 m
    assert ghost_offset_m(SIM_META) == pytest.approx(5276.0, abs=1)
    assert ghost_offset_m({"heading_deg": 10.0}) == (4000.0, 8000.0)


def test_heading_from_meta_or_clear_error():
    assert azimuth_heading({"heading_deg": 350}) == 350.0
    with pytest.raises(ValueError, match="TODO"):
        azimuth_heading({"orbit_direction": "ASCENDING"})


def _ghost_hits(offset_from_meta: bool):
    hits = boats_flagged = n = 0
    for seed in range(10):
        s = make_scene(seed, shape=(1200, 1200), n_ships=2, n_boats=5)
        img = to_linear(s.vv)
        mu = background(img)
        c = clusters(flag(img, mu, alpha(4.4)), img, mu, meta=s.meta)
        offset = ghost_offset_m(s.meta) if offset_from_meta else ghost_offset_m({})
        heading = azimuth_heading(s.meta)
        for g in s.ghosts.itertuples():
            near = c[np.hypot(c["row"] - g.row, c["col"] - g.col) <= 2]
            n += 1
            hits += len(near) > 0 and is_ghost(near.iloc[0], img, heading, offset)
        for b in s.boats.itertuples():
            near = c[np.hypot(c["row"] - b.row, c["col"] - b.col) <= 2]
            boats_flagged += len(near) > 0 and is_ghost(near.iloc[0], img, heading, offset)
    return hits / n, boats_flagged


def test_simulator_ghosts_flagged_at_least_80pct():
    rate, boats_flagged = _ghost_hits(offset_from_meta=True)
    assert rate >= 0.8
    assert boats_flagged == 0  # real boats with no bright partner are never ghosts


def test_band_search_without_prf_still_flags_ghosts():
    assert _ghost_hits(offset_from_meta=False)[0] >= 0.8


def test_ship_itself_is_not_a_ghost():
    s = make_scene(1, shape=(1200, 1200), n_ships=1)
    img = to_linear(s.vv)
    g = s.ghosts.iloc[0]
    ship = {
        "row": g.ship_row,
        "col": g.ship_col,
        "peak_db": 10 * np.log10(img[int(g.ship_row), int(g.ship_col)]),
    }
    assert not is_ghost(ship, img, 350.0, ghost_offset_m(s.meta))
