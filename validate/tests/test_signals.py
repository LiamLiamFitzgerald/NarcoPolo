"""L2 per-signal agents (docs/learning.md): kappa, merge rule, no look-ahead, and a real season on the simulator."""

import json

import numpy as np
import pandas as pd
import pytest

from core import io
from core.config import load
from validate import signals
from validate.signals import AGENTS, BACKTEST_COLUMNS, _one, backtest_agent, kappa, merge


def test_kappa_is_one_with_itself_and_near_zero_for_unrelated_flags():
    rng = np.random.default_rng(0)
    a = pd.Series(rng.random(2000) < 0.3)
    assert kappa(a, a) == 1.0
    assert abs(kappa(a, pd.Series(rng.random(2000) < 0.3))) < 0.1
    assert kappa(a, ~a) < 0


def test_merge_is_a_transitive_partition_best_agent_first():
    k = pd.DataFrame(0.0, index=list("abcd"), columns=list("abcd"))
    for x, y in [
        ("a", "b"),
        ("b", "c"),
    ]:  # a~b and b~c, so a, b, c are one group even though a !~ c
        k.loc[x, y] = k.loc[y, x] = 0.9
    groups = merge(k, 0.7, {"a": 0.1, "b": 0.5, "c": 0.3, "d": 0.2})
    assert sorted(a for g in groups for a in g) == list("abcd")
    assert ["b", "c", "a"] in groups and ["d"] in groups


def test_walk_forward_ranks_each_week_on_its_own_scores():
    week = lambda d, labels, scores: pd.DataFrame(
        {"cell_id": ["x", "y", "z"], "date": d, "label": labels, "gi": scores}
    )
    rows = pd.concat(
        [
            week("2026-01-04", [False, False, False], [3, 2, 1]),
            week("2026-01-11", [False, True, False], [1, 5, 2]),
        ],
        ignore_index=True,
    )
    m = _one("gi", rows, k=1)
    assert m["precision_at_k"] == 0.5 and m["recall"] == 1.0 and m["weeks_to_detect"] == 0.0
    later = rows.copy()
    later.loc[later["date"] == "2026-01-11", "gi"] = [9, 0, 0]  # change only the second week
    assert _one("gi", later.iloc[:3], k=1) == _one(
        "gi", rows.iloc[:3], k=1
    )  # first week unaffected
    assert m["false_alerts_per_week"] == 0.5


@pytest.fixture(scope="module")
def season_env(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_REPORTS", str(tmp_path_factory.mktemp("reports")))
    signals._season.cache_clear()
    yield
    signals._season.cache_clear()
    mp.undo()


def test_every_agent_backtests_on_the_simulator(season_env):
    out = pd.concat([backtest_agent(a, "fixed", [1]) for a in AGENTS], ignore_index=True)
    assert list(out.columns) == BACKTEST_COLUMNS and len(out) == len(AGENTS)
    assert (out["precision_at_k"].between(0, 1)).all()
    assert (out["recall"] > 0).any()  # at least one statistic sees the planted site
    with pytest.raises(ValueError):
        backtest_agent("link", "fixed", [1])  # R3: site-level, not backtested here


def test_report_has_metrics_kappa_and_merged_groups(season_env):
    path = signals.write_signals_report([1])
    rep = json.loads(path.read_text())
    assert sorted(a for g in rep["merged"] for a in g) == sorted(AGENTS)
    assert all(rep["kappa"][a][a] == 1.0 for a in AGENTS)
    assert rep["config_hash"] == load(io.CONFIG_PATH)[1]
    if "null" in rep["regimes"] or rep["null"]:
        assert all(v == sorted(v) for v in rep["null"].values())
