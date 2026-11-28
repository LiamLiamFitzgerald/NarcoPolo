import json

import numpy as np
import pandas as pd
import pytest

from core import io
from core.config import load
from sim.simulate import simulate
from validate import (
    calibration,
    interval_coverage,
    recall_curve,
    run,
    simulator_recovery,
    wilson,
    write_report,
)


@pytest.fixture(scope="module")
def sim_world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("w")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    mp.setenv("NARCO_REPORTS", str(tmp / "reports"))
    simulate(load(io.CONFIG_PATH)[0], 20261127)
    yield tmp
    mp.undo()


def test_wilson_known_values():
    lo, hi = wilson(5, 10)
    assert abs(lo - 0.2366) < 1e-3 and abs(hi - 0.7634) < 1e-3
    assert wilson(0, 10)[0] == 0.0 and abs(wilson(0, 10)[1] - 0.2775) < 1e-3
    assert wilson(0, 0) == (0.0, 1.0)


def test_calibration_recovers_a_calibrated_forecast_and_merges_thin_bins():
    rng = np.random.default_rng(0)
    p = rng.random(20000)
    table, brier = calibration(p, rng.random(20000) < p)
    assert len(table) == 10 and (table["mean_pred"] - table["observed"]).abs().max() < 0.05
    assert abs(brier - 1 / 6) < 0.01  # Brier of a calibrated uniform forecast
    thin, _ = calibration(np.array([0.05] * 30 + [0.55] * 5 + [0.95] * 30), np.zeros(65))
    assert (thin["n"] >= 20).all() and thin["n"].sum() == 65


def test_interval_coverage_of_the_true_poisson_rates_on_slowdowns(sim_world):
    obs, exp = io.read_stage("aggregate/observed"), io.read_stage("forecast/expected")
    fine = obs["level"] == 2000
    cov = interval_coverage(
        exp[exp["event_type"] == "slowdown"], obs[fine & (obs["event_type"] == "slowdown")]
    )
    assert (
        0.88 <= cov <= 0.92
    )  # PIT coverage of the true rates is about 0.9 (the raw count measure gave ~0.99)


def _frames(C, mu, phi):
    n = len(C)
    key = {
        "cell_id": [f"c{i}" for i in range(n)],
        "date": ["2026-11-01"] * n,
        "event_type": "slowdown",
    }
    obs = pd.DataFrame({**key, "count": C, "exposure": 1.0})
    exp = pd.DataFrame({**key, "mu": mu, "phi": phi, "fold": pd.array([0] * n, dtype="Int64")})
    return exp, obs


def test_pit_coverage_is_the_target_level_for_the_true_poisson_and_nb_rates():
    # #226 known answer: counts drawn from the forecast itself cover 90%, even at tiny mu where P(0) > 0.95
    rng = np.random.default_rng(0)
    mu = rng.choice([0.004, 0.05, 0.5, 3.0], 200_000)
    exp, obs = _frames(rng.poisson(mu).astype(float), mu, 1.0)
    assert interval_coverage(exp, obs, 0.9) == pytest.approx(0.9, abs=0.005)
    from scipy.stats import poisson

    lo, hi = poisson.ppf(0.05, mu), poisson.ppf(0.95, mu)
    raw = ((obs["count"] >= lo) & (obs["count"] <= hi)).mean()
    assert (
        raw > 0.95
    )  # the old "count in [lo90, hi90]" measure: well above 0.9 for a calibrated forecast
    phi = 3.0  # negative binomial, variance phi * mu
    nb = rng.negative_binomial(mu / (phi - 1), 1 / phi).astype(float)
    exp, obs = _frames(nb, mu, phi)
    assert interval_coverage(exp, obs, 0.9) == pytest.approx(0.9, abs=0.005)


def test_pit_coverage_sees_intervals_that_are_too_wide():
    rng = np.random.default_rng(1)
    mu = rng.choice([0.5, 3.0], 100_000)
    exp, obs = _frames(
        rng.poisson(mu).astype(float), mu, 4.0
    )  # phi overstated: the forecast is too spread out
    assert interval_coverage(exp, obs, 0.9) > 0.95
    backtest_only = exp.assign(fold=pd.array([1] * len(exp), dtype="Int64"))
    assert np.isnan(
        interval_coverage(backtest_only, obs, 0.9)
    )  # backtest folds are not the live forecast


def test_recall_curve_counts_every_boat_in_a_footprint(sim_world):
    truth = pd.read_parquet(io.truth_path())
    det = io.read_stage("detect/detections")
    calm = io.read_stage("coverage/exposure").groupby("pass_id")["calm"].first().to_dict()
    r = recall_curve(det, truth, calm)
    inside = truth[
        (truth["kind"] != "drop") & (truth["pass_index"] >= 0) & (truth["length_m"] < 24)
    ]
    assert r["n"].sum() == len(inside) and len(r) == 8
    seen = r[r["n"] > 0]
    assert ((seen["lo"] <= seen["recall"]) & (seen["recall"] <= seen["hi"])).all()
    # recall of boats the simulator really detected is high, and longer boats are easier
    assert (
        r[r["length_bin"] == "12-15"]["detected"].sum() / r[r["length_bin"] == "12-15"]["n"].sum()
        > r[r["length_bin"] == "<8"]["detected"].sum() / r[r["length_bin"] == "<8"]["n"].sum()
    )


def test_simulator_recovery_finds_the_planted_site_and_the_rates(sim_world):
    rec = simulator_recovery()
    assert rec["planted_site_rank"] == 1
    for event_type, ratio in rec["observed_over_expected"].items():
        assert 0.8 <= ratio <= 1.2, event_type


def test_run_writes_a_report_with_every_key(sim_world, monkeypatch):
    # fuse is real since #184, so the report's null test now runs fuse on shifted data; 2 runs keep this test
    # quick (make validate keeps the spec's 200; validate/tests/test_null.py tests the null test itself)
    import functools

    import validate.checks
    from validate.null import null_test

    monkeypatch.setattr(validate.checks, "null_test", functools.partial(null_test, runs=2))
    # L6 runs whole simulated seasons through the real pipeline (tens of minutes); validate/tests/test_policy.py
    # covers it, and this test checks the report's keys and blocks, so the policy block is left out here
    monkeypatch.setattr(validate.checks, "policy_block", lambda: None)
    path = run()
    rep = json.loads(path.read_text())
    assert {"recall", "injection", "skill", "calibration", "brier", "null"} <= set(rep)
    null = rep["null"]
    assert null["runs"] == 2 and 0 <= null["share_with_any_flag"] <= 1
    assert null["lo"] <= null["share_with_any_flag"] <= null["hi"]
    assert rep["recovery"]["planted_site_rank"] == 1 and 0 <= rep["brier"] <= 1


def test_report_turns_nan_into_null(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_REPORTS", str(tmp_path))
    rep = json.loads(
        write_report(
            {"brier": float("nan"), "recall": pd.DataFrame({"recall": [np.nan, 0.5]})}
        ).read_text()
    )
    assert rep["brier"] is None and rep["recall"] == [{"recall": None}, {"recall": 0.5}]
