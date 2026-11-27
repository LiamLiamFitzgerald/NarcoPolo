import shutil

import pandas as pd

from core import io
from core.config import load
from sim.simulate import simulate


def _sim(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    cfg_path = tmp_path / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg_path)
    monkeypatch.setattr(io, "CONFIG_PATH", cfg_path)
    simulate(load(cfg_path)[0], 20261127)


def test_run_entry_points_round_trip_sim_files(tmp_path, monkeypatch):
    import detect
    import match

    _sim(tmp_path, monkeypatch)
    before = {n: io.read_stage(n) for n in ("detect/detections", "match/events")}
    detect.run()
    match.run()
    for name, frame in before.items():
        pd.testing.assert_frame_equal(io.read_stage(name), frame)
