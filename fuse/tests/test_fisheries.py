"""#321 (P6 side): the fisheries lens, against small stand-ins for #344-#346 and #322, plus the simulator gate."""

import shutil

import numpy as np
import pandas as pd
import pytest

from core import io, schemas
from core.config import load
from fuse.fisheries import COLUMNS, _gated, _weekly, fisheries
from sim.simulate import simulate

_DAYS = pd.date_range("2026-11-02", periods=7)  # Monday .. Sunday: one ISO week
_NORMAL = [f"n{i}" for i in range(20)]


def _frames():
    """Stand-in aggregate/observed and forecast/expected: one hot cell (3 medium boats a day where 0.2 are expected),
    20 normal cells, one unobserved cell and a planted drop pattern (dark_small surplus, normal dark_medium)."""
    obs, exp = [], []

    def add(cell, kind, count, mu, exposure=1.0):
        for d in _DAYS:
            obs.append({"cell_id": cell, "level": 2000, "date": d, "event_type": kind, "count": count,
                        "exposure": exposure})  # fmt: skip
            exp.append({"cell_id": cell, "date": d, "event_type": kind, "mu": mu, "phi": 2.0, "lo90": 0.0,
                        "hi90": 1.0, "model": "stand-in", "fold": 0})  # fmt: skip

    add("hot", "dark_medium", 3.0, 0.2)
    for c in _NORMAL:
        add(c, "dark_medium", 0.2, 0.2)
    add("dark", "dark_medium", 0.0, 0.2, exposure=0.0)  # unobserved: never a zero
    add("drop", "dark_medium", 0.2, 0.2)
    add("drop", "dark_small", 4.0, 0.1)
    o, e = pd.DataFrame(obs), pd.DataFrame(exp)
    coarse = o[o["cell_id"] == "n0"].assign(level=10000, count=50.0)  # coarse level: ignored
    backtest = e[e["cell_id"] == "hot"].assign(mu=50.0, fold=1)  # backtest fold: ignored
    return pd.concat([o, coarse], ignore_index=True), pd.concat([e, backtest], ignore_index=True)


_TRAVEL = pd.DataFrame(
    {
        "cell_id": ["hot"] * 5 + ["drop"],
        "pier_id": ["far", "near", "track", "mid", "farther", "near"],
        "hours": [2.0, 0.5, 0.1, 1.0, 3.0, 0.2],
    }
)
_PIERS = pd.DataFrame(
    {
        "pier_id": ["far", "near", "track", "mid", "farther"],
        "road_access": [True, True, False, True, True],
    }
)


def test_known_answer_hot_cell_is_the_only_candidate():
    """count 21 vs mu 1.4 over the week: lowest p_mid, flagged, first candidate; normal cells are not."""
    obs, exp = _frames()
    w = _weekly(obs, exp).set_index("cell_id")
    assert "dark" not in w.index  # exposure 0 gives no row, never a zero
    assert w["p_mid"].idxmin() == "hot" and w.at["hot", "flag"] and not w.loc[_NORMAL, "flag"].any()
    out = fisheries(obs, exp, _TRAVEL, _PIERS)
    assert list(out.columns) == COLUMNS and out["cell_id"].tolist() == ["hot"]
    c = out.iloc[0]
    assert c["week"] == pd.Timestamp("2026-11-02").date() and c["lens"] == "fisheries"
    assert c["count"] == pytest.approx(21.0) and c["mu"] == pytest.approx(1.4)
    assert c["y_fish"] == pytest.approx(21.5 / 1.9)
    assert c["y_fish_lo"] == pytest.approx(21.5 / 7.5)  # sum of hi90 = 7
    assert c["y_fish_hi"] == pytest.approx(21.5 / 0.5)  # sum of lo90 = 0


def test_does_not_take_the_drop_site():
    """The planted drop cell has a dark_small surplus but normal dark_medium: never a fisheries candidate."""
    obs, exp = _frames()
    assert "drop" not in set(fisheries(obs, exp, _TRAVEL, _PIERS)["cell_id"])


def test_p_mid_is_the_detectors_tail_with_weekly_sums():
    from detectors.scores import tail_pmid

    obs, exp = _frames()
    w = _weekly(obs, exp).set_index("cell_id")
    assert w.at["hot", "p_mid"] == pytest.approx(float(tail_pmid([21.0], [1.4], [2.0])[0]))


@pytest.mark.parametrize(
    ("closed", "want", "line"),
    [
        (
            pd.DataFrame({"cell_id": ["hot"], "in_closed_area": [True]}),
            True,
            "Inside a closed area.",
        ),
        (
            pd.DataFrame({"cell_id": ["hot"], "in_closed_area": [False]}),
            False,
            "Outside closed areas.",
        ),
        (
            pd.DataFrame({"cell_id": ["n0"], "in_closed_area": [True]}),
            None,
            "Closed areas unknown here.",
        ),
        (None, None, "Closed areas unknown here."),
    ],
)
def test_in_closed_area_true_false_or_unknown(closed, want, line):
    obs, exp = _frames()
    c = fisheries(obs, exp, _TRAVEL, _PIERS, closed=closed).iloc[0]
    assert pd.isna(c["in_closed_area"]) if want is None else c["in_closed_area"] == want
    assert line in c["reasons"]


def test_harbours_nearest_by_sea_road_access_only():
    obs, exp = _frames()
    c = fisheries(obs, exp, _TRAVEL, _PIERS).iloc[0]
    assert c["top_harbours"] == ["near", "mid", "far"]  # 'track' is nearer but has no road access
    assert c["top_harbours_hours"] == [0.5, 1.0, 2.0]


def test_no_reachable_harbour_says_so():
    obs, exp = _frames()
    c = fisheries(obs, exp, _TRAVEL[_TRAVEL["cell_id"] == "drop"], _PIERS).iloc[0]
    assert c["top_harbours"] == [] and c["top_harbours_hours"] == []
    assert "No road-access harbour within reach by sea." in c["reasons"]


def test_reasons_follow_the_language_rule():
    obs, exp = _frames()
    c = fisheries(obs, exp, _TRAVEL, _PIERS).iloc[0]
    text = " ".join(c["reasons"]).lower()
    assert "21 where 1.4 were expected" in text and "worth checking" in text
    assert not any(w in text for w in ("smuggling", "illegal", "detected"))


def test_no_medium_rows_gives_an_empty_frame():
    obs, exp = _frames()
    out = fisheries(obs[obs["event_type"] == "dark_small"], exp, _TRAVEL, _PIERS)
    assert out.empty and list(out.columns) == COLUMNS


def test_gate_needs_the_schema_and_dark_medium_rows(monkeypatch):
    obs, exp = _frames()
    small_only = obs[obs["event_type"] == "dark_small"]
    monkeypatch.delitem(
        schemas.SCHEMAS, "fuse/fisheries", raising=False
    )  # off without the schema (#346)
    assert _gated(obs, exp, _TRAVEL, _PIERS) is None
    monkeypatch.setitem(
        schemas.SCHEMAS, "fuse/fisheries", schemas.SCHEMAS["fuse/sites"]
    )  # stand-in entry
    assert _gated(small_only, exp, _TRAVEL, _PIERS) is None
    pd.testing.assert_frame_equal(
        _gated(obs, exp, _TRAVEL, _PIERS), fisheries(obs, exp, _TRAVEL, _PIERS)
    )


def test_simulator_run_writes_fisheries_only_when_schema_and_inputs_exist(tmp_path):
    """fuse.run() writes fuse/fisheries exactly when core/schemas declares it and the simulator has dark_medium rows
    (#346); either way fuse/sites stays schema-valid. Holds before and after #346 lands."""
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp_path / "data"))
    cfg = tmp_path / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    mp.setattr(io, "CONFIG_PATH", cfg)
    try:
        simulate(load(cfg)[0], 20261127)
        import fuse

        fuse.run()
        schemas.check("fuse/sites", io.read_stage("fuse/sites"))
        has_input = bool(np.any(io.read_stage("aggregate/observed")["event_type"] == "dark_medium"))
        if "fuse/fisheries" in schemas.SCHEMAS and has_input:
            f = io.read_stage("fuse/fisheries")  # read_stage re-checks the schema
            assert (f["lens"] == "fisheries").all()
        else:
            assert not list((tmp_path / "data").rglob("*fisheries*"))
    finally:
        mp.undo()
