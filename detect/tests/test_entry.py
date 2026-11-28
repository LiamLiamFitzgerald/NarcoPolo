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


def _real(monkeypatch):
    real = lambda name: "real"
    monkeypatch.setattr(io, "read_provenance", real)


def test_real_detect_refits_pboat_from_training_before_the_cutoff(tmp_path, monkeypatch):
    import detect
    import detect.pipeline

    _sim(tmp_path, monkeypatch)
    seen = {}

    def run_all(model, exposure):
        seen["model"] = model
        return io.read_stage("detect/detections")

    monkeypatch.setattr(detect.pipeline, "run_all", run_all)
    _real(monkeypatch)
    detect.run()
    m = seen["model"]
    assert set(m.logit.params.index) >= {"peak_ratio_vv_db", "wind_ms"}  # wind joined from exposure
    assert m.logit.nobs > 0 and len(io.read_stage("detect/detections"))


def test_real_match_writes_dark_small_and_presence_slowdowns(tmp_path, monkeypatch):
    import match
    from match._common import CFG

    _sim(tmp_path, monkeypatch)
    # the simulator labels the slow bin "0-2" and types cargo/tanker; real GFW is "<2" and cargo/carrier (#239)
    monkeypatch.setitem(CFG, "presence_slow_bins", ["0-2"])
    monkeypatch.setitem(CFG, "presence_vessel_types", ["cargo", "tanker"])
    _real(monkeypatch)
    match.run()
    ev = io.read_stage("match/events")
    assert {"dark_small", "slowdown"} <= set(ev["event_type"])
    slow = ev[ev["event_type"] == "slowdown"]
    assert slow["duration_min"].gt(0).all() and slow["ship_key"].isna().all()
    assert not ev[ev["event_type"] == "dark_small"]["matched"].any()
    # #344: every unmatched medium detection is also a dark_medium event, and stays in dark_small
    dets = io.read_stage("detect/detections")
    medium = set("dark_medium-" + dets.loc[dets["size_class"] == "medium", "det_id"])
    dm = ev[ev["event_type"] == "dark_medium"]
    ds = set(ev.loc[ev["event_type"] == "dark_small", "event_id"])
    assert len(dm) and set(dm["event_id"]) <= medium and not dm["matched"].any()
    assert set(dm["event_id"].str.replace("dark_medium-", "dark_small-")) <= ds
