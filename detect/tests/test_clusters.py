import numpy as np
import pandas as pd

from detect._standin import make_scene
from detect.cfar import alpha, background, clusters, flag, merge_pols, size_class
from detect.scene import to_linear
from detect.tests.test_run import _hits


def _cands(s):
    out = []
    for raw in (s.vv, s.vh):
        img = to_linear(raw)
        mu = background(img)
        out.append(clusters(flag(img, mu, alpha(4.4)), img, mu, meta=s.meta))
    return merge_pols(*out)


def _recall(cands, boats):
    return float(_hits(cands, boats).mean())


def test_planted_bright_boats_recovered():
    # 15 dB boats sit far above alpha (7.5 dB): the planted detection rate is 1, recovery must be >= 0.9
    rec, false = [], 0
    for seed in range(5):
        s = make_scene(seed, shape=(500, 500), n_boats=20, boat_excess_db=15.0)
        c = _cands(s)
        rec.append(_recall(c, s.boats))
        false += len(c) - round(rec[-1] * 20)
    assert np.mean(rec) >= 0.9
    assert false <= 5  # ~0.05 expected false pixels per pass per pol at p_fa = 1e-7


def test_recall_rises_with_brightness():
    rates = [np.mean([_recall(_cands(s := make_scene(seed, (500, 500), n_boats=30, boat_excess_db=ex)), s.boats)
                      for seed in range(3)]) for ex in (3.0, 6.0, 15.0)]  # fmt: skip
    assert rates[0] < rates[1] < rates[2]  # measured 0.0, 0.39, 1.0


def test_pol_merge_pairs_within_gate_and_keeps_max_px():
    vv = pd.DataFrame({"row": [0, 10.0], "col": [0, 0.0], "x_m": [0, 1000.0], "y_m": [0, 0.0], "n_px": [2, 3],
                       "peak_ratio_db": [10.0, 11.0], "peak_db": [-5.0, -4.0]})  # fmt: skip
    vh = pd.DataFrame({"row": [1.0], "col": [1.0], "x_m": [20.0], "y_m": [0.0], "n_px": [5], "peak_ratio_db": [9.0],
                       "peak_db": [-12.0]})  # fmt: skip
    m = merge_pols(vv, vh, gate_m=30)
    assert len(m) == 2
    paired = m[m["pol_agree"]].iloc[0]
    assert paired["n_px"] == 5 and paired["peak_ratio_vh_db"] == 9.0 and paired["x_m"] == 0
    assert np.isnan(m[~m["pol_agree"]].iloc[0]["peak_ratio_vh_db"])


def test_size_class_bounds():
    assert list(size_class([1, 4, 5, 20, 21])) == ["small", "small", "medium", "medium", "large"]
    assert size_class(3) == "small"


def test_clusters_drop_blobs_over_200_px():
    mask = np.zeros((50, 50), bool)
    mask[:15, :15] = True  # 225 px
    mask[40, 40] = True
    img = np.ones((50, 50))
    c = clusters(mask, img, img, meta={"x_left": 0.0, "y_top": 500.0})
    assert list(c["n_px"]) == [1]
    assert c.iloc[0]["x_m"] == 405 and c.iloc[0]["y_m"] == 95
