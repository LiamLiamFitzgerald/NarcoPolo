"""R3: the site model's features are the trainer's weekly agent scores, per site, from observed cells only."""

import shutil

import numpy as np
import pandas as pd
import pytest

from core import io
from core.config import load
from fuse.features import AGENTS, site_features, weekly_scores
from sim.simulate import simulate


@pytest.fixture(scope="module")
def season(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("feat")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    cfg = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    mp.setattr(io, "CONFIG_PATH", cfg)
    simulate(load(cfg)[0], 20261127)
    yield (
        io.read_stage("aggregate/observed"),
        io.read_stage("forecast/expected"),
        io.read_snapshot()["T"],
    )
    mp.undo()


def test_site_features_are_the_agents_in_order_from_the_latest_observed_week(season):
    obs, exp, T = season
    w = weekly_scores(obs, exp)
    cells = w["cell_id"].drop_duplicates().iloc[:5].tolist()
    sites = pd.DataFrame({"site_id": [*cells, "2000_9999_9999"]}, index=range(10, 16))
    f = site_features(sites, obs, exp, T)
    assert list(f.columns) == list(AGENTS) and list(f.index) == list(sites.index)
    assert np.isfinite(f.iloc[:5].to_numpy()).all()  # observed cells have every score
    assert f.iloc[5].isna().all()  # a never-observed cell is unknown, never zero (principle 4)
    last = w[w["cell_id"] == cells[0]].sort_values("date").iloc[-1]
    assert f.iloc[0].to_numpy() == pytest.approx(last[list(AGENTS)].to_numpy(float))


def test_site_features_ignore_weeks_after_T(season):
    obs, exp, _ = season
    w = weekly_scores(obs, exp)
    early = pd.Timestamp(w["date"].min())
    cell = w.loc[w["date"] > early, "cell_id"].iloc[0]
    f = site_features(pd.DataFrame({"site_id": [cell]}), obs, exp, early.date())
    first = w[(w["cell_id"] == cell) & (w["date"] <= early)]
    assert (
        f.iloc[0].isna().all()
        if first.empty
        else f.iloc[0]["oe"] == pytest.approx(first["oe"].iloc[-1])
    )


def test_weekly_scores_use_the_live_forecast_only(season):
    """#172/#198: only fold == 0 is the live forecast. A backtest fold or a row with no fold must not add a
    second mu for the same cell-day (it would double the weekly expected count)."""
    obs, exp, _ = season
    live = exp[exp["fold"] == 0]
    extra = pd.concat(
        [
            live.assign(fold=pd.array([1] * len(live), dtype="Int64"), mu=live["mu"] * 50),
            live.assign(fold=pd.array([None] * len(live), dtype="Int64"), mu=live["mu"] * 50),
        ]
    )
    base = weekly_scores(obs, live)
    noisy = weekly_scores(obs, pd.concat([live, extra], ignore_index=True))
    pd.testing.assert_frame_equal(base.reset_index(drop=True), noisy.reset_index(drop=True))
