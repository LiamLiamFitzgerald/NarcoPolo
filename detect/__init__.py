"""P4 detect: radar scenes to small-boat candidates with p_boat."""

from core import io
from core.config import load
from core.split import Split, folds


def _split() -> Split:
    """The level-2 split every small-boat fit uses: the oldest dark_small backtest fold's cut-off."""
    s = load(io.CONFIG_PATH)[0]["split"]
    T = io.read_snapshot()["T"]
    return Split(folds(T, s["n_folds_small"])[-1].cutoff, s["embargo_days"], s["test_days"])


def run() -> None:
    """make all entry point (DECISIONS.md 2026-11-27 18:30).

    Simulator: `make sim` already wrote detect/detections, and its chips only draw the boats the simulator
    decided were detected, inside a small window, so re-detecting them would shrink coverage, not test anything.
    The file is re-validated and kept, like reference and coverage do. validate.injection_test runs the real
    detector (detect.pipeline.run_pass) on the simulator's chips.
    Real data: p_boat is refitted from validate/pboat_training on every run (DECISIONS.md 28 Nov 11:30, #209),
    then every scene in coverage/exposure is detected.
    """
    if io.read_provenance("coverage/exposure") == "simulated":
        io.write_stage("detect/detections", io.read_stage("detect/detections"), "simulated")
        return
    from detect.pboat import features, fit_pboat
    from detect.pipeline import run_all

    exposure = io.read_stage("coverage/exposure")
    train = io.read_stage("validate/pboat_training")
    train = train.assign(wind_ms=features(train, exposure)["wind_ms"])
    model = fit_pboat(train, _split())
    io.write_stage("detect/detections", run_all(model, exposure), "real")
