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
    assert 0.88 <= cov <= 1.0  # the 90% Poisson range is a little conservative for discrete counts


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


def test_run_writes_a_report_with_every_key(sim_world):
    path = run()
    rep = json.loads(path.read_text())
    assert {"recall", "injection", "skill", "calibration", "brier", "null"} <= set(rep)
    assert rep["null"] == {"runs": 0, "share_with_any_flag": None}
    assert rep["recovery"]["planted_site_rank"] == 1 and 0 <= rep["brier"] <= 1


def test_report_turns_nan_into_null(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_REPORTS", str(tmp_path))
    rep = json.loads(
        write_report(
            {"brier": float("nan"), "recall": pd.DataFrame({"recall": [np.nan, 0.5]})}
        ).read_text()
    )
    assert rep["brier"] is None and rep["recall"] == [{"recall": None}, {"recall": 0.5}]
