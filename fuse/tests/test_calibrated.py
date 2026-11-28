"""#61 acceptance: p_site (the rung-1 site model, docs/learning.md L4) has a lower Brier score than the uncalibrated
percentile rank of S on held-out simulator runs, with a reliability table from P1's validate.checks.calibration.

The stack is fitted with validate/train.py's own code on the train regimes (config learn.regimes.train), level-2
training weeks only (core.Split, no look-ahead), and written to models/site_model.json in a scratch data root, where
fuse.learn applies it. Held-out = the regimes in learn.regimes.held_out, never fitted on. They are scored the way
fuse ships them: fuse's (sites, piers, links) at each Sunday t of the scored weeks (the trainer's split), with
observed rows and events cut at t. The outcome is the trainer's label: a planted drop in the site's cell in the week
ending t. Expectations are the season's live forecast (P5's, not fitted here) for both scores alike.
Tests import validate, which tach allows in tests only (tach.toml excludes **/tests)."""

import json

import numpy as np
import pandas as pd
import pytest

from core import io
from core.config import load
from fuse.features import AGENTS
from fuse.link import _all
from validate import train
from validate.checks import calibration

pytestmark = (
    pytest.mark.slow
)  # whole simulated seasons, about 3 min (28 Nov); run with `pytest -m slow`

SEED = 1
_NAMES = (
    "aggregate/observed",
    "forecast/expected",
    "reference/cells",
    "reference/travel_hours",
    "match/events",
)


def _write_model(cfg, sha) -> None:
    """Rung 1 fitted on the train regimes' level-2 training weeks, saved in train.fit_site_model's format."""
    features = list(AGENTS)
    seasons = [train._site_weeks(cfg, r, SEED) for r in cfg["learn"]["regimes"]["train"]]
    rows = pd.concat([train._train(r, s) for r, s in seasons], ignore_index=True)
    X, y = rows[features].to_numpy(float), rows["label"].to_numpy(float)
    fit = train._fit(1, X, y, train._params(cfg), SEED)
    model = {"rung": 1, "features": features, **train._weights(fit, features), "config_hash": sha}
    path = train.model_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(train._plain(model)))


def _scored_weeks(cfg, regime: str) -> pd.DataFrame:
    """One held-out season: per Sunday t of its scored weeks, fuse's sites at t with p_site, rank of S, label."""
    train._simulate(cfg, SEED, regime)
    obs, exp, layers, travel, events = (io.read_stage(n) for n in _NAMES)
    truth = pd.read_parquet(io.truth_path())
    T = pd.Timestamp(io.read_snapshot()["T"])
    split = train._split(cfg, T)
    start = pd.Timestamp(split.cutoff) + pd.Timedelta(days=split.embargo_days)
    ev_t = pd.to_datetime(events["time_utc"], utc=True).dt.tz_convert(None)
    out = []
    for t in pd.date_range(start, T, freq="W-SUN"):
        o = obs[pd.to_datetime(obs["date"]) <= t]
        e = events[ev_t < t + pd.Timedelta(days=1)]
        s = _all(o, exp, layers, travel, e, None, t.date())[0]
        out.append(
            pd.DataFrame(
                {
                    "p_site": s["p_site"].to_numpy(float),
                    "rank_S": s["S"].rank(pct=True).to_numpy(float),
                    "rung": s["model_rung"].to_numpy(int),
                    "label": train._labels(
                        pd.DataFrame({"cell_id": s["site_id"], "date": t}), truth
                    ).to_numpy(float),
                }
            )
        )
    return pd.concat(out, ignore_index=True)


@pytest.fixture(scope="module")
def held_out(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p6cal")
    mp = pytest.MonkeyPatch()
    for k, d in (("NARCO_DATA", "data"), ("NARCO_RAW", "raw"), ("NARCO_REPORTS", "reports")):
        mp.setenv(k, str(tmp / d))
    try:
        cfg, sha = load(io.CONFIG_PATH)
        _write_model(cfg, sha)
        held = cfg["learn"]["regimes"]["held_out"]
        assert not set(held) & set(cfg["learn"]["regimes"]["train"])
        yield pd.concat([_scored_weeks(cfg, r) for r in held], ignore_index=True)
    finally:
        mp.undo()


def test_the_fitted_site_model_is_applied(held_out):
    assert (held_out["rung"] == 1).all()  # rung 1 from the file, not the rung-0 fallback


def test_p_site_beats_the_rank_of_S_on_brier_on_held_out_runs(held_out):
    y = held_out["label"].to_numpy()
    assert y.sum() > 0  # a planted drop is scored, so the outcome is not all "no drop"
    table, brier_p = calibration(held_out["p_site"].to_numpy(), y)
    _, brier_rank = calibration(held_out["rank_S"].to_numpy(), y)
    assert np.isfinite(brier_p) and len(table) > 0
    assert brier_p < brier_rank
