"""Fixed-target suppression for the small-boat CFAR (#334), on a simulated stack of passes. This is the spec for
P4's median-ratio step: P4 implements it in detect, and these numbers are what it must reproduce."""

import numpy as np
import pytest

from core.config import load
from sim.stack import fixed_target_stack
from validate.fixed_targets import compare, median_ratio, summary

SEED = 20261127


@pytest.fixture(scope="module")
def cfg():
    return load("config.yaml")[0]


@pytest.fixture(scope="module")
def result(cfg):
    stack = fixed_target_stack(cfg, SEED)
    return stack, compare(stack, cfg)


def test_stack_has_fixed_targets_in_the_same_pixels_and_new_boats_each_pass(cfg, result):
    stack, _ = result
    f = cfg["sim"]["fixed_targets"]
    assert stack.images.shape == (f["n_passes"], f["size_px"], f["size_px"])
    r, c = stack.fixed[:, 0], stack.fixed[:, 1]
    assert (stack.images[:, r, c] > 10 ** (f["fixed_db"] / 10) * 0.5).all()  # bright on every pass
    lo, hi = cfg["sim"]["pickup_length_m"]
    assert stack.boats["length_m"].between(lo, hi).all()
    assert stack.boats.groupby("pass").size().eq(f["boats_per_pass"]).all()
    assert stack.boats.duplicated(["row", "col"]).mean() < 0.05  # boats move between passes


def test_median_ratio_finds_more_small_boats_without_more_fixed_target_alarms(result):
    _, per_pass = result
    s = summary(per_pass)
    print("\n" + s.to_string())  # the measurement, for the PR and for P4
    rec, fa = s["recall"].to_dict(), s["fa_fixed"].to_dict()
    assert rec["median_ratio"] > rec["baseline"]
    assert fa["median_ratio"] <= fa["baseline"]


def test_open_sea_false_alarms_are_measured_not_hidden(result):
    # The ratio image's speckle has a heavier tail than gamma(L), so p_fa on it is not the nominal rate.
    # Reported (finite, per km2) so P4 calibrates the threshold on this, not on the nominal p_fa.
    _, per_pass = result
    s = summary(per_pass)
    assert np.isfinite(s["fa_sea_per_km2"]).all()


def test_an_earlier_pass_never_sees_a_later_one(cfg):
    stack = fixed_target_stack(cfg, SEED)
    n = cfg["validate"]["fixed_target_history"]
    before = compare(stack, cfg)
    later = stack.images.copy()
    later[n + 1 :] *= 50.0  # change every pass after pass n beyond recognition
    changed = compare(type(stack)(later, stack.fixed, stack.boats), cfg)
    k = before["pass"] == n
    assert before[k].equals(changed[k])
    np.testing.assert_array_equal(median_ratio(stack.images, n, n), median_ratio(later, n, n))


def test_the_median_needs_enough_earlier_passes(cfg):
    stack = fixed_target_stack(cfg, SEED)
    with pytest.raises(ValueError, match="earlier passes"):
        median_ratio(stack.images, 2, 3)
