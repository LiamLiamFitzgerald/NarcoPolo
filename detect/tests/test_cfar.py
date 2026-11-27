import numpy as np

from detect._standin import make_scene
from detect.cfar import alpha, background, estimate_enl, flag
from detect.scene import apply_masks, to_linear

SEA = 0.01


def _sea(seed, shape=(1000, 1000), L=4.4):
    return SEA * np.random.default_rng(seed).gamma(L, 1 / L, size=shape)


def test_enl_recovers_simulator_looks():
    assert abs(estimate_enl(_sea(0), (slice(None), slice(None))) - 4.4) < 0.1


def test_background_recovers_sea_level():
    mu = background(_sea(1))
    assert np.isclose(np.nanmean(mu[50:-50, 50:-50]), SEA, rtol=0.01)


def test_background_ignores_a_boat_inside_the_guard():
    img = _sea(2, (200, 200))
    img[100, 100] += 1000 * SEA
    assert np.isclose(
        background(img)[100, 100], np.median(background(_sea(2, (200, 200)))), rtol=0.1
    )


def test_background_next_to_land_is_not_biased():
    # NaN land must not count as zero: the ring next to the coast still sees sea level
    s = make_scene(seed=3, shape=(300, 300), land_cols=100)
    img = apply_masks(to_linear(s.vv), s.land, s.static)
    mu = background(img)
    first_sea_col = np.argmax(np.isfinite(img[150]))
    assert np.isclose(mu[150, first_sea_col], 0.01, rtol=0.15)


def test_alpha_is_the_gamma_tail():
    a = alpha(4.4, 1e-3)
    tail = (np.random.default_rng(4).gamma(4.4, 1 / 4.4, size=2_000_000) > a).mean()
    assert np.isclose(tail, 1e-3, rtol=0.1)


def test_false_alarm_rate_on_pure_sea():
    # p_fa = 1e-3 so the rate is measurable on 1e6 pixels; the estimated ring inflates it a little
    img = _sea(5)
    m = flag(img, background(img), alpha(4.4, 1e-3))[20:-20, 20:-20]
    assert 0.8e-3 < m.mean() < 1.4e-3


def test_nan_pixels_are_never_flagged():
    img = _sea(6, (100, 100))
    img[:, :10] = np.nan
    assert not flag(img, background(img), alpha(4.4))[:, :10].any()
