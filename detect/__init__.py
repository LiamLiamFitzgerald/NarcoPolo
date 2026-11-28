"""P4 detect: radar scenes to small-boat candidates with p_boat."""

from core import io


def run() -> None:
    """make all entry point (DECISIONS.md 2026-11-27 18:30).

    Simulator: `make sim` already wrote detect/detections, and its chips only draw the boats the simulator
    decided were detected, inside a small window, so re-detecting them would shrink coverage, not test anything.
    The file is re-validated and kept, like reference and coverage do. validate.injection_test runs the real
    detector (detect.pipeline.run_pass) on the simulator's chips.
    Real data: detect.pipeline.run_all needs a fitted p_boat model, and where it is fitted and stored is not
    decided yet (TODO(P1), #183).
    """
    if io.read_provenance("coverage/exposure") == "simulated":
        io.write_stage("detect/detections", io.read_stage("detect/detections"), "simulated")
        return
    raise NotImplementedError(
        "detect on real data: the p_boat model's home is not decided (TODO(P1), #183)"
    )
