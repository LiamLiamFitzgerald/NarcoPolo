import hashlib
import shutil
from pathlib import Path

import pandas as pd
import pytest

from core import io
from core.config import load
from sim.simulate import NX, NY, _p_det, simulate


def run(tmp: Path, monkeypatch, seed: int = 20261127) -> Path:
    data = tmp / "data"
    monkeypatch.setenv("NARCO_DATA", str(data))
    cfg_path = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg_path)
    monkeypatch.setattr(io, "CONFIG_PATH", cfg_path)
    simulate(load(cfg_path)[0], seed)
    return data


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    data = run(tmp_path_factory.mktemp("a"), mp)
    yield data, mp
    mp.undo()


def test_detection_probability_matches_spec():
    cfg, _ = load("config.yaml")
    assert abs(_p_det(cfg, 10, 3) - 0.18) < 0.01
    assert abs(_p_det(cfg, 15, 2) - 0.73) < 0.01


def test_same_seed_same_files(world, tmp_path_factory):
    data, mp = world
    first = {
        p.relative_to(data): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in data.rglob("*.parquet")
    }
    cells = io.read_stage("reference/cells")
    other = run(tmp_path_factory.mktemp("b"), mp)
    second = {
        p.relative_to(other): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in other.rglob("*.parquet")
    }
    assert first == second and len(first) == 11  # 10 stage files + truth
    assert io.read_stage("reference/cells").equals(cells)
    run(
        tmp_path_factory.mktemp("c"), mp, seed=1
    )  # leave the module fixture's data in place for later tests
    mp.setenv("NARCO_DATA", str(data))


def test_every_stage_file_reads_back_valid(world):
    data, mp = world
    mp.setenv("NARCO_DATA", str(data))
    for name in io.SCHEMAS:
        assert len(io.read_stage(name)) > 0
    cells = io.read_stage("reference/cells")
    assert (cells["level"] == 2000).sum() == NX * NY
    assert (
        len(io.read_stage("reference/piers")) == 6
        and io.read_stage("reference/piers")["road_access"].sum() == 3 + 1
    )


def test_truth_has_planted_drops_about_every_10_days(world):
    data, _ = world
    truth = pd.read_parquet(data / "sim" / "truth.parquet")
    drops = truth[truth["kind"] == "drop"]["time_utc"].sort_values()
    assert 9 <= len(drops) <= 13
    assert 8 <= drops.diff().dt.days.dropna().min() and drops.diff().dt.days.max() <= 12
    assert (truth["kind"] == "pickup").sum() >= 0.5 * len(drops)  # 0.8 expected
    assert truth[truth["kind"] == "drop"]["cell_id"].nunique() == 1


def test_unobserved_rows_are_kept_with_zero_count(world):
    data, mp = world
    mp.setenv("NARCO_DATA", str(data))
    obs = io.read_stage("aggregate/observed")
    unseen = obs[obs["exposure"] == 0]
    assert len(unseen) > 0 and (unseen["count"] == 0).all()
    assert obs.groupby(["level", "event_type"]).size().nunique() > 0


def test_no_raw_ship_identifier_in_any_file(world):
    data, mp = world
    mp.setenv("NARCO_DATA", str(data))
    ev = io.read_stage("match/events")
    assert ev["ship_key"].dropna().str.fullmatch("[0-9a-f]{16}").all()
    assert not {"mmsi", "imo", "name", "call_sign"} & set(ev.columns)


def test_no_dark_small_event_on_a_rough_pass(world):  # #90: rough passes look for nobody
    data, mp = world
    mp.setenv("NARCO_DATA", str(data))
    ex = io.read_stage("coverage/exposure")
    ev = io.read_stage("match/events")
    rough = set(ex.loc[~ex["calm"], "time_utc"])
    assert rough and not ev[ev["event_type"] == "dark_small"]["time_utc"].isin(rough).any()
    assert not io.read_stage("detect/detections")["time_utc"].isin(rough).any()


def test_new_contract_files_keep_their_invariants(world):  # #87, #88, #98
    data, mp = world
    mp.setenv("NARCO_DATA", str(data))
    sites, links = io.read_stage("fuse/sites"), io.read_stage("fuse/links")
    s = links.assign(w=links["L"] * 0.5 ** (links["age_days"] / 30)).groupby("site_id")["w"].sum()
    assert (s.reindex(sites["site_id"]).fillna(0) - sites["S"].to_numpy()).abs().max() < 1e-9
    assert set(io.read_stage("fuse/piers")["pier_id"]) == set(
        io.read_stage("reference/piers")["pier_id"]
    )
    cells = io.read_stage("fuse/cells")
    assert (cells["y"] > 0).all() and (cells["y_week"] > 0).all()
