"""L6 policy evaluation (docs/learning.md): does a learning patrol find drops sooner than a fixed ranking?

Each season is walked week by week: sites from fuse.run on data up to the cutoff -> node weights from the
policy -> the same routes for every policy -> sim.patrol_outcome -> bandit update (bandit policy only).
Regret is pseudo-regret against the oracle: the true drop count at the sites the oracle visits minus that at
the sites the policy visits, so the thinning of finds (learn.p_find_*) does not add noise to it.
Only visited sites ever count (principle 3); scores are per site, never per vessel (principle 5).
"""

import importlib
import json
import os
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import entropy

from core import io
from core.config import load

POLICIES = ("fixed_S", "fixed_p_site", "bandit", "oracle", "random")
COLUMNS = [
    "policy", "regime", "seed", "regret", "weeks_to_first_find", "finds_per_patrol_hour",
    "coverage_entropy",
]  # fmt: skip
_NAMES = (
    "aggregate/observed",
    "forecast/expected",
    "reference/cells",
    "reference/travel_hours",
    "match/events",
)
WEEK = pd.Timedelta(days=7)


@dataclass(frozen=True)
class _Season:
    """One simulated season: truth, weekly cutoffs, candidate sites at a cutoff, and the route planner."""

    truth: pd.DataFrame
    weeks: Sequence[pd.Timestamp]
    sites_at: Callable[[pd.Timestamp], pd.DataFrame]  # site_id, S, p_site (+ what route needs)
    route: Callable[
        [pd.DataFrame, np.ndarray, pd.Timestamp], tuple[dict, float]
    ]  # -> (plan, hours)


@dataclass(frozen=True)
class _Deps:
    world: Callable[[str, int], _Season]
    outcome: Callable[
        [pd.DataFrame, dict, pd.Timestamp], pd.DataFrame
    ]  # sim.patrol_outcome(truth, plan, week_start): R2, the week's start timestamp (UTC)
    bandit: Any  # patrol.bandit: prior(sites, n0), update(state, outcomes, discount, week=), sample(state, seed)


def _true_counts(truth: pd.DataFrame, cutoff: pd.Timestamp) -> pd.Series:
    """Drops per site_id in the patrol week after the cutoff (truth only; for the oracle and regret)."""
    t = pd.to_datetime(truth["time_utc"], utc=True)
    c = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff
    d = truth[(truth["kind"] == "drop") & (t > c) & (t <= c + WEEK)]
    return d.groupby("site_id").size()


def _entropy(visits: pd.Series) -> float:
    """Shannon entropy (nats) of visit counts per site; log(n) when n sites are visited equally."""
    return float(entropy(visits.to_numpy(float))) if visits.sum() > 0 else float("nan")


def _seed(seed: int, week: int) -> int:
    return int(np.random.SeedSequence((seed, week)).generate_state(1)[0])


def _visited(out: pd.DataFrame) -> pd.Series:
    return out.loc[out["visited"].astype(bool), "site_id"]


def _season(
    policies: Iterable[str], regime: str, seed: int, deps: _Deps, cfg: Any
) -> list[dict[str, Any]]:
    s = deps.world(regime, seed)
    learn = cfg["learn"]
    rows = []
    for policy in policies:
        if policy not in POLICIES:
            raise ValueError(f"unknown policy {policy!r}; one of {POLICIES}")
        state: dict = {}
        regret, finds, hours, first = 0.0, 0, 0.0, float("nan")
        visits: list[pd.Series] = []
        for w, cutoff in enumerate(s.weeks):
            cands = s.sites_at(cutoff).reset_index(drop=True)
            true = _true_counts(s.truth, cutoff)
            oracle_w = (
                true.reindex(cands["site_id"]).fillna(0).to_numpy(float)
            )  # truth: no drop = 0
            if policy == "bandit":
                state = {**deps.bandit.prior(cands, learn["prior_strength"]), **state}
                weights = deps.bandit.sample(state, _seed(seed, w)).reindex(cands["site_id"])
                weights = weights.to_numpy(float)
            elif policy == "oracle":
                weights = oracle_w
            elif policy == "random":
                weights = np.random.default_rng(_seed(seed, w)).random(len(cands))
            else:
                weights = cands[policy.removeprefix("fixed_")].to_numpy(float)
            plan, h = s.route(cands, weights, cutoff)
            start = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff  # R2: week start
            out = deps.outcome(s.truth, plan, start)
            if policy == "bandit":  # the only caller of bandit.update; week= fills last_visit_week
                state = deps.bandit.update(state, out, learn["discount"], week=w)
            best = deps.outcome(s.truth, s.route(cands, oracle_w, cutoff)[0], start)
            regret += float(
                true.reindex(_visited(best)).fillna(0).sum()
                - true.reindex(_visited(out)).fillna(0).sum()
            )
            found = int(out["found"].astype(bool).sum())
            if found and np.isnan(first):
                first = w + 1
            finds, hours = finds + found, hours + h
            visits.append(_visited(out))
        counts = pd.concat(visits).value_counts() if visits else pd.Series(dtype=float)
        rows.append(
            {
                "policy": policy,
                "regime": regime,
                "seed": seed,
                "regret": regret,
                "weeks_to_first_find": first,
                "finds_per_patrol_hour": finds / hours if hours > 0 else float("nan"),
                "coverage_entropy": _entropy(counts),
            }
        )
    return rows


def _evaluate(
    policies: Iterable[str], regime: str, seeds: Iterable[int], deps: _Deps
) -> pd.DataFrame:
    cfg, _ = load(io.CONFIG_PATH)
    rows = [r for seed in seeds for r in _season(list(policies), regime, seed, deps, cfg)]
    return pd.DataFrame(rows, columns=COLUMNS)


def evaluate(policy: str, regime: str, seeds: Iterable[int]) -> pd.DataFrame:
    """One row per seed: regret vs the oracle, weeks to first find, finds per patrol-hour, coverage entropy."""
    deps = _real_deps()
    if deps is None:
        raise ImportError(
            "needs sim.patrol_outcome (#150), patrol.bandit (#151), fuse.learn (#152)"
        )
    return _evaluate([policy], regime, seeds, deps)


def _summary(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Mean and standard deviation across seeds per policy and regime."""
    metrics = COLUMNS[3:]
    g = frame.groupby(["policy", "regime"])[metrics]
    m, sd = g.mean(), g.std()
    out = m.add_suffix("_mean").join(sd.add_suffix("_sd")).reset_index()
    return [
        {str(k): v for k, v in r.items()}
        for r in out.assign(n_seeds=g.size().to_numpy()).to_dict("records")
    ]


def _block(deps: _Deps | None = None) -> dict[str, Any] | None:
    """The `policy` block of reports/validation.json, train and held-out regimes kept apart.
    None while a dependency (#150, #151, #152) is missing."""
    deps = deps or _real_deps()
    if deps is None:
        return None
    learn = load(io.CONFIG_PATH)[0]["learn"]
    seeds = range(
        int(learn["n_seeds_quick"])
    )  # R5: make validate; the final report uses learn.n_seeds
    return {
        split: _summary(
            pd.concat([_evaluate(POLICIES, r, seeds, deps) for r in learn["regimes"][split]])
        )
        for split in ("train", "held_out")
    }


def _module(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _attr(module: str, name: str) -> Any:
    return getattr(_module(module), name, None)


def _real_deps() -> _Deps | None:
    """The real modules, imported lazily so validate runs before #150, #151 and #152 land."""
    outcome = _attr("sim", "patrol_outcome")
    bandit = _module("patrol.bandit")
    site_value = _attr("fuse.learn", "site_value")
    if (
        outcome is None
        or site_value is None
        or not all(hasattr(bandit, f) for f in ("prior", "update", "sample"))
    ):
        return None
    return _Deps(world=_real_world, outcome=outcome, bandit=bandit)


def _real_world(regime: str, seed: int) -> _Season:  # pragma: no cover - runs once #150-#152 land
    """Simulate one season into a temporary data root and keep everything the weekly loop needs in memory."""
    patrol = importlib.import_module("patrol")
    fuse = importlib.import_module("fuse")
    site_value = importlib.import_module("fuse.learn").site_value
    simulate = importlib.import_module("sim.simulate").simulate
    cfg, _ = load(io.CONFIG_PATH)
    model_path = io.ROOT / "models" / "site_model.json"
    model = json.loads(model_path.read_text()) if model_path.exists() else None  # None: rung 0
    old = {k: os.environ.get(k) for k in ("NARCO_DATA", "NARCO_RAW")}
    with tempfile.TemporaryDirectory(prefix="narco-policy-") as tmp:
        os.environ["NARCO_DATA"], os.environ["NARCO_RAW"] = f"{tmp}/data", f"{tmp}/raw"
        try:
            simulate(cfg, seed, regime=regime)
            frames = {k: io.read_stage(k) for k in _NAMES}
            truth = pd.read_parquet(io.truth_path())
            # shortcut: patrol's private base and sea grid; switch when P7 makes them public.
            base, _ = patrol._base(cfg)
            sea = patrol._sea_from_cells(frames["reference/cells"])
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    obs, exp, ev = frames["aggregate/observed"], frames["forecast/expected"], frames["match/events"]
    days = pd.to_datetime(obs["date"])
    weeks = list(pd.date_range(days.min() + pd.Timedelta(days=6), days.max() - WEEK, freq="7D"))

    def sites_at(cutoff: pd.Timestamp) -> pd.DataFrame:
        end = cutoff.tz_localize("UTC") + pd.Timedelta(days=1)
        _, sites = fuse.run(
            obs[pd.to_datetime(obs["date"]) <= cutoff],
            exp[pd.to_datetime(exp["date"]) <= cutoff],
            frames["reference/cells"],
            frames["reference/travel_hours"],
            ev[ev["time_utc"] < end],
        )
        sites = sites.assign(p_site=site_value(sites, model))
        return sites.nlargest(int(cfg["learn"]["alert_budget"]), "p_site")  # the bandit's arms (L5)

    def route(cands: pd.DataFrame, weights: np.ndarray, cutoff: pd.Timestamp) -> tuple[dict, float]:
        start = cutoff.tz_localize("UTC") + pd.Timedelta(days=1)
        c = cands.assign(S=weights)
        plan = {
            "ship": patrol._plan_asset(
                c, base, lambda n: patrol.sea_hours(n, sea, patrol.SHIP_KN),
                budget_h=patrol.SHIP_BUDGET_H, dwell_h=patrol.SHIP_DWELL_H, start=start,
            ),
            "aircraft": patrol._plan_asset(
                c, base, lambda n: patrol.air_hours(n, patrol.AIR_KN),
                budget_h=patrol.AIR_BUDGET_H, dwell_h=patrol.AIR_DWELL_H, start=start,
            ),
        }  # fmt: skip
        hours = sum(
            (
                pd.Timestamp(st[-1]["arrival_utc"]) - pd.Timestamp(st[0]["arrival_utc"])
            ).total_seconds()
            / 3600
            for st in plan.values()
        )
        return plan, hours

    return _Season(truth=truth, weeks=weeks, sites_at=sites_at, route=route)
