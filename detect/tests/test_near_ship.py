"""#267: recall of a small boat at set distances from a large ship, plain vs censored CFAR ring.

Gamma sea (simulator L = 4.4), one bright ship bar under the 200 px cap, one 15 dB boat (far above alpha's 7.5 dB, so
open-water recall is ~1), abeam at a set distance from the ship's nearest edge. Measured before this change: recall
0.00 within ~200 m of a 20-30 dB ship with the plain ring (the ring is +-205 m), 1.00 beyond.
"""

import numpy as np
import pytest

from detect._common import CFG
from detect.cfar import _censored_background, alpha, background, clusters, flag, merge_pols
from detect.scene import to_linear
from detect.tests._scene import SIM_SEA_DB, make_scene

PX = CFG["pixel_m"]
GATE_PX = 3.0  # a candidate within 30 m of the boat counts as recovering it
BOAT_DB = 15.0
A = alpha(CFG["enl"], CFG["p_fa"])


def _cands(vv, vh, meta, censor):
    out = []
    for img in (vv, vh):
        mu = _censored_background(img, A) if censor else background(img)
        out.append(clusters(flag(img, mu, A), img, mu, meta=meta))
    return merge_pols(*out)


def _plant(img, rows, cols, db, sea):
    img[rows, cols] += sea * (10 ** (db / 10) - 1)


def recall_at(edge_m, ship_db=30.0, ship_len_px=40, ship_w_px=4, censor=True, seeds=range(20)):
    """Share of seeds whose boat is a small or medium candidate within GATE_PX; ship_w_px = 0 means no ship."""
    hits = 0
    for seed in seeds:
        s = make_scene(seed, shape=(300, 300))
        vv, vh = to_linear(s.vv), to_linear(s.vh)
        r0, c0 = (
            150 - ship_len_px // 2,
            150 - ship_w_px // 2,
        )  # ship: vertical bar centred on the chip
        br = 150
        bc = c0 + ship_w_px - 1 + round(edge_m / PX) if ship_w_px else 150
        for img, pol in ((vv, "vv"), (vh, "vh")):
            sea = 10 ** (SIM_SEA_DB[pol] / 10)
            if ship_w_px:
                _plant(img, slice(r0, r0 + ship_len_px), slice(c0, c0 + ship_w_px), ship_db, sea)
            _plant(img, slice(br, br + 1), slice(bc, bc + 1), BOAT_DB, sea)
        c = _cands(vv, vh, s.meta, censor)
        small = c[c["n_px"] <= CFG["size_medium_max_px"]]  # the boat's own blob, not the ship's
        hits += bool(len(small)) and bool(
            (np.hypot(small["row"] - br, small["col"] - bc) <= GATE_PX).any()
        )
    return hits / len(seeds)


def test_open_water_control_is_near_one():
    assert recall_at(0, ship_w_px=0) >= 0.95


@pytest.mark.parametrize("ship_db", [20.0, 30.0])
@pytest.mark.parametrize("edge_m", [50, 100, 150])
def test_censored_ring_finds_boats_the_plain_ring_loses_next_to_a_ship(edge_m, ship_db):
    assert recall_at(edge_m, ship_db, censor=False) <= 0.1  # the #267 blind spot
    assert recall_at(edge_m, ship_db, censor=True) >= 0.9


def test_censoring_leaves_open_sea_background_unchanged():
    s = make_scene(3, shape=(300, 300))
    img = to_linear(s.vv)
    plain, cens = background(img), _censored_background(img, A)
    assert np.nanmax(np.abs(cens / plain - 1)) < 1e-3
