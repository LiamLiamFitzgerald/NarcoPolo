import pandas as pd
import pytest

from core.config import load
from core.io import CONFIG_PATH
from sim.patrol import COLUMNS, patrol_outcome
from sim.simulate import simulate

T = pd.Timestamp("2026-03-01T12:00:00Z")
TRUTH = pd.DataFrame(
    {
        "kind": ["drop", "boat"],
        "time_utc": [T, T],
        "site_id": ["site_0", None],
        "active": [True, False],
    }
)


def plan(*ids: str) -> dict:
    return {"ship": [{"id": i, "arrival_utc": "2026-03-01T14:00:00Z", "dwell_h": 1} for i in ids]}


def test_only_planned_stops_get_rows():
    out = patrol_outcome(TRUTH, plan("site_0", "site_9"), week=9)
    assert list(out.columns) == COLUMNS
    assert (
        set(out["site_id"]) == {"site_0", "site_9"} and out["visited"].all()
    )  # site_7 etc.: no row at all
    assert not out.loc[out["site_id"] == "site_9", "found"].any()  # no drop there


def test_same_week_same_outcome_and_far_visits_find_nothing():
    a, b = patrol_outcome(TRUTH, plan("site_0"), 9), patrol_outcome(TRUTH, plan("site_0"), 9)
    assert a.equals(b)
    late = {"ship": [{"id": "site_0", "arrival_utc": "2026-03-05T12:00:00Z", "dwell_h": 1}]}
    assert not patrol_outcome(TRUTH, late, 9)["found"].any()  # outside learn.find_window_h


def test_unbuilt_regimes_say_where_they_are_built():
    cfg, _ = load(CONFIG_PATH)
    with pytest.raises(NotImplementedError, match="#150"):
        simulate(cfg, 1, regime="null")
    with pytest.raises(ValueError):
        simulate(cfg, 1, regime="nope")
