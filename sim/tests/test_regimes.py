from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from core import io
from core.config import load
from sim import patrol_outcome
from sim.simulate import simulate

DAYS = 60  # a short season keeps the suite fast; two_sites still has two halves


def _config(tmp: Path, days: int = DAYS, **learn) -> Path:
    cfg = yaml.safe_load((io.ROOT / "config.yaml").read_text())
    cfg["sim"]["days"] = days
    cfg["learn"].update(learn)
    path = tmp / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def _run(tmp: Path, mp: pytest.MonkeyPatch, regime: str, seed: int) -> tuple[Path, pd.DataFrame]:
    data = tmp / "data"
    mp.setenv("NARCO_DATA", str(data))
    path = _config(tmp)
    mp.setattr(io, "CONFIG_PATH", path)
    simulate(load(path)[0], seed, regime=regime)
    return data, pd.read_parquet(io.truth_path())


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    out = {
        (r, s): _run(tmp_path_factory.mktemp(f"{r}{s}"), mp, r, s)
        for r, s in [
            ("null", 1),
            ("fixed", 1),
            ("two_sites", 1),
            ("pass_aware", 1),
            ("pass_aware", 2),
            ("displacing", 1),
            ("displacing", 2),
        ]
    }
    yield out, mp
    mp.undo()


def _drops(truth: pd.DataFrame) -> pd.DataFrame:
    return truth[truth["kind"] == "drop"].sort_values("time_utc")


def _xy(cell_id: str) -> np.ndarray:
    _, ix, iy = cell_id.split("_")
    return np.array([int(ix), int(iy)]) * 2.0  # km, fine cells


def test_every_row_carries_the_regime_and_each_drop_its_site(runs):
    out, _ = runs
    for (regime, _seed), (_, truth) in out.items():
        assert (truth["regime"] == regime).all()
        d = _drops(truth)
        assert (d["site_id"] == d["cell_id"]).all() and d["active"].all()
        assert truth.loc[~truth["kind"].isin(["drop", "visit"]), "site_id"].isna().all()


def test_unknown_regime_raises_before_writing_anything():
    with pytest.raises(ValueError, match="unknown regime"):
        simulate(load(io.ROOT / "config.yaml")[0], 1, regime="nope")


def test_fixed_truth_has_one_site(runs):
    out, _ = runs
    assert _drops(out[("fixed", 1)][1])["site_id"].nunique() == 1


def test_null_has_no_drops_and_every_file_validates(runs):
    out, mp = runs
    data, truth = out[("null", 1)]
    assert not (truth["kind"].isin(["drop", "pickup", "visit"])).any()
    mp.setenv("NARCO_DATA", str(data))
    mp.setattr(io, "CONFIG_PATH", data.parent / "config.yaml")
    for name in io.SCHEMAS:
        io.read_stage(name)  # raises on a broken file
    assert io.read_stage("fuse/sites").empty and (io.read_stage("fuse/piers")["P_j"] == 0).all()
    assert (
        not io.read_stage("match/events").query("event_type == 'slowdown'").empty
    )  # normal ships remain


def test_two_sites_switch_at_half_season(runs):
    out, _ = runs
    d = _drops(out[("two_sites", 1)][1])
    day = (d["time_utc"] - d["time_utc"].min().normalize()).dt.days
    first, second = d[day < DAYS / 2 - 8]["site_id"], d[day >= DAYS / 2 + 8]["site_id"]
    assert first.nunique() == 1 and second.nunique() == 1
    assert first.iloc[0] != second.iloc[0]


@pytest.mark.parametrize("seed", [1, 2])
def test_pass_aware_drops_keep_away_from_passes(runs, seed):
    out, mp = runs
    data, truth = out[("pass_aware", seed)]
    mp.setenv("NARCO_DATA", str(data))
    mp.setattr(io, "CONFIG_PATH", data.parent / "config.yaml")
    passes = io.read_stage("coverage/exposure")["time_utc"].drop_duplicates().to_numpy()
    buf = pd.Timedelta(hours=load(io.CONFIG_PATH)[0]["learn"]["pass_buffer_h"])
    d = _drops(truth)["time_utc"].to_numpy()
    assert len(d) >= 4
    gap = np.abs(d[:, None] - passes[None, :]).min(axis=1)
    assert (gap >= buf.to_timedelta64()).all()


@pytest.mark.parametrize("seed", [1, 2])
def test_displacing_moves_to_a_neighbour_after_a_visit(runs, seed):
    out, _ = runs
    truth = out[("displacing", seed)][1]
    km = load(io.ROOT / "config.yaml")[0]["learn"]["displace_km"]
    d, visits = _drops(truth), truth[truth["kind"] == "visit"]
    checked = 0
    for v in visits.itertuples():
        after = d[d["time_utc"] > v.time_utc]
        if after.empty:
            continue
        nxt = after.iloc[0]["site_id"]
        assert nxt != v.site_id and np.hypot(*(_xy(nxt) - _xy(v.site_id))) <= km
        before = d[d["time_utc"] < v.time_utc]
        assert (
            before.empty or before.iloc[-1]["site_id"] == v.site_id
        )  # the visit was at the active site
        checked += 1
    assert checked >= 2


# patrol_outcome


def _stop(sid: str, t: str) -> dict:
    return {"id": sid, "arrival_utc": t, "dwell_h": 1}


WEEK = pd.Timestamp("2026-08-03", tz="UTC")
TRUTH = pd.DataFrame(
    {
        "kind": ["drop", "drop", "pickup"],
        "time_utc": pd.to_datetime(
            ["2026-08-04T10:00Z", "2026-08-06T10:00Z", "2026-08-04T12:00Z"], utc=True
        ),
        "site_id": ["2000_1_1", "2000_2_2", None],
        "active": [True, True, False],
    }
)
PLAN = {
    "ship": [
        _stop("base", "2026-08-04T06:00:00Z"),
        _stop("2000_1_1", "2026-08-04T20:00:00Z"),  # 10 h after a drop
        _stop("2000_3_3", "2026-08-04T22:00:00Z"),  # no drop ever
        _stop("2000_2_2", "2026-08-20T10:00:00Z"),  # outside the week
    ],
    "aircraft": [_stop("2000_2_2", "2026-08-06T09:00:00Z")],
}


@pytest.fixture
def p_find(tmp_path, monkeypatch):
    def set_(ship: float, aircraft: float) -> None:
        monkeypatch.setattr(
            io, "CONFIG_PATH", _config(tmp_path, p_find_ship=ship, p_find_aircraft=aircraft)
        )

    return set_


def test_outcome_only_has_visited_sites_and_finds_nearby_drops(p_find):
    p_find(1.0, 1.0)
    out = patrol_outcome(TRUTH, PLAN, WEEK)
    assert list(out.columns) == ["site_id", "asset", "visited", "found"]
    assert set(zip(out["site_id"], out["asset"], out["found"], strict=True)) == {
        ("2000_1_1", "ship", True),
        ("2000_3_3", "ship", False),
        ("2000_2_2", "aircraft", True),
    }
    assert out["visited"].all()  # unvisited sites (and the base) get no row


def test_outcome_misses_with_zero_find_probability_and_ignores_inactive(p_find):
    p_find(0.0, 0.0)
    assert not patrol_outcome(TRUTH, PLAN, WEEK)["found"].any()
    p_find(1.0, 1.0)
    quiet = TRUTH.assign(active=False)
    assert not patrol_outcome(quiet, PLAN, WEEK)["found"].any()


def test_outcome_thinning_recovers_p_find_and_is_deterministic(p_find):
    p_find(0.8, 0.5)
    weeks = [WEEK + pd.Timedelta(days=7 * k) for k in range(400)]
    truth = pd.DataFrame(
        {
            "kind": "drop",
            "time_utc": [w + pd.Timedelta(hours=30) for w in weeks],
            "site_id": "2000_1_1",
            "active": True,
        }
    )
    found = {"ship": [], "aircraft": []}
    for w in weeks:
        t = (w + pd.Timedelta(hours=32)).strftime("%Y-%m-%dT%H:%M:%SZ")
        plan = {"ship": [_stop("2000_1_1", t)], "aircraft": [_stop("2000_1_1", t)]}
        out = patrol_outcome(truth, plan, w)
        assert out.equals(patrol_outcome(truth, plan, w))  # same inputs, same outcomes
        for asset, hit in zip(out["asset"], out["found"], strict=True):
            found[str(asset)].append(bool(hit))
    # 400 draws: 3 standard errors is about 0.06 at p = 0.8 and 0.075 at p = 0.5
    assert abs(np.mean(found["ship"]) - 0.8) < 0.06
    assert abs(np.mean(found["aircraft"]) - 0.5) < 0.075


def test_outcome_on_simulated_truth(runs, p_find):
    out, _ = runs
    truth = out[("fixed", 1)][1]
    drop = _drops(truth).iloc[2]
    week = drop["time_utc"].normalize() - pd.Timedelta(days=1)
    t = (drop["time_utc"] + pd.Timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    p_find(1.0, 1.0)
    plan = {"ship": [_stop(drop["site_id"], t)]}
    res = patrol_outcome(truth, plan, week)
    assert res["found"].tolist() == [True]
    assert patrol_outcome(truth, {"ship": []}, week).empty
