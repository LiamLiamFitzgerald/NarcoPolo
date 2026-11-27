"""P4 detect: radar scenes to small-boat candidates with p_boat."""

from core import io


def run() -> None:
    """make all entry point (DECISIONS.md 2026-11-27 18:30).

    Stub: passes the simulated detect/detections through core.io, which re-validates it.
    TODO(P4): call detect.pipeline.run_all once the p_boat model's home is fixed and P3's exposure lands.
    """
    io.write_stage("detect/detections", io.read_stage("detect/detections"), "simulated")
