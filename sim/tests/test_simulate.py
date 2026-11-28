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


@pytest.mark.slow
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
    assert first == second and len(first) == 13  # 12 stage files + truth
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
    assert (
        io.read_stage("forecast/expected")["fold"] == 0
    ).all()  # live forecast, like forecast.run (#172)
    cells = io.read_stage("reference/cells")
    assert (cells["level"] == 2000).sum() == NX * NY
    assert (
        len(io.read_stage("reference/piers")) == 6
        and io.read_stage("reference/piers")["road_access"].sum() == 3 + 1
    )


def test_truth_has_planted_drops_about_every_10_days_at_irregular_times(world):
    data, _ = world
    truth = pd.read_parquet(data / "sim" / "truth.parquet")
    drops = truth[truth["kind"] == "drop"]["time_utc"].sort_values()
    gaps = drops.diff().dt.total_seconds().dropna() / 86400
    assert 5 <= len(drops) <= 20 and 6 <= gaps.mean() <= 16  # mean drop_interval_days = 10
    assert gaps.min() >= 0.9 and gaps.std() > 2  # a Poisson process, not a fixed cadence (#177)
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


@pytest.mark.slow
def test_pickups_use_pickup_length_m_and_only_pickups_change(tmp_path):
    """#266: validate's visible world sets sim.pickup_length_m; the default equals small_boat_length_m."""
    cfg, _ = load("config.yaml")
    assert (
        cfg["sim"]["pickup_length_m"] == cfg["sim"]["small_boat_length_m"]
    )  # the default world is unchanged
    mp = pytest.MonkeyPatch()
    out = {}
    for name, length in (("small", cfg["sim"]["pickup_length_m"]), ("big", [25, 50])):
        mp.setenv("NARCO_DATA", str(tmp_path / name / "data"))
        mp.setenv("NARCO_RAW", str(tmp_path / name / "raw"))
        simulate({**cfg, "sim": {**cfg["sim"], "pickup_length_m": length}}, 20261127)
        out[name] = pd.read_parquet(io.truth_path())
    mp.undo()
    small, big = out["small"], out["big"]
    p = big[big["kind"] == "pickup"]["length_m"]
    assert len(p) and p.between(25, 50).all()
    keep = ["kind", "time_utc", "x_m", "y_m"]
    pd.testing.assert_frame_equal(
        small[keep], big[keep]
    )  # same places and times: only pick-up size differs
    assert (
        big.loc[big["kind"] == "pickup", "detected"].mean()
        > small.loc[small["kind"] == "pickup", "detected"].mean()
    )


def test_weather_daily_covers_every_cell_day_with_the_day_weather(world):  # #208
    data, mp = world
    mp.setenv("NARCO_DATA", str(data))
    wd, cells = io.read_stage("coverage/weather_daily"), io.read_cells()
    ex = io.read_stage("coverage/exposure")
    assert len(wd) == (cells["level"] == 2000).sum() * wd["date"].nunique()
    on_pass = wd.merge(ex.assign(date=ex["time_utc"].dt.tz_localize(None).dt.normalize()))
    assert len(on_pass) == len(ex)  # every pass's cell-day has weather
    assert (on_pass["wind_max_ms"] - on_pass["wind_ms"]).abs().max() < 1e-5
    assert (on_pass["hs_max_m"] - on_pass["hs_m"]).abs().max() < 1e-5


def test_dist_coast_is_measured_to_the_shoreline():
    """#245: the shoreline sits SHORE_FRAC into the shore row; the shore row's centre is 200 m from it, not 1000."""
    from sim.simulate import FINE, NY, SHORE_FRAC, _make_map

    fine = _make_map(load("config.yaml")[0])["fine"]
    shore = fine.loc[fine["iy"] == NY - 1, "dist_coast_m"]
    assert shore.eq(SHORE_FRAC * FINE - FINE / 2).all()
    assert (
        fine.loc[fine["iy"] == NY - 1, "inshore_frac"].eq(1).all()
    )  # the inshore band did not move
