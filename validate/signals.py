"""Per-signal agents and their backtests (docs/learning.md L2).

Each statistical property is an "agent" scored on its own: weekly per-cell scores from the simulator (oe = log y,
midp = -log10 mid-p, gi = weekly Gi* z, cusum = Poisson CUSUM; R3), the same scores validate.train fits on.
`link` is site-level only (R3) and enters through p_comb, so it is not backtested here.

Outputs reports/signals.json: per-agent metrics per regime, the kappa / Spearman matrices, the merged groups fuse
uses as CCT votes (best agent first, which validate.train uses as the group's feature), and per-agent null samples
from `null`-regime runs, which fuse turns into site-level p values (#164).
"""

import json
import logging
import os
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from core import io
from core.config import load
from validate import train

AGENTS = train._AGENTS  # one definition of the scores, shared with the trainer
BACKTEST_COLUMNS = [
    "agent",
    "regime",
    "seed",
    "precision_at_k",
    "recall",
    "weeks_to_detect",
    "false_alerts_per_week",
]
NULL_MAX = 10_000  # most null samples kept per agent (#164)
log = logging.getLogger(__name__)


def kappa(a: pd.Series, b: pd.Series) -> float:
    """Cohen's kappa of two yes/no flag columns: (agreement - chance agreement) / (1 - chance agreement)."""
    x, y = a.to_numpy(bool), b.to_numpy(bool)
    po = float(np.mean(x == y))
    pe = float(x.mean() * y.mean() + (1 - x.mean()) * (1 - y.mean()))
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


@cache
def _season(regime: str, seed: int) -> pd.DataFrame:
    """Weekly agent scores per observed cell, with labels (an active drop in that cell that week). Cached: every
    agent's backtest and the overlap read the same simulated season."""
    cfg, _ = load(io.CONFIG_PATH)
    rows, _split = train._site_weeks(cfg, regime, seed)
    return rows


def _topk(week: pd.DataFrame, agent: str, k: int) -> pd.Index:
    """The k cells with the highest score that week (ties broken by cell id, so it is repeatable)."""
    return week.sort_values([agent, "cell_id"], ascending=[False, True]).head(k).index


def _one(agent: str, rows: pd.DataFrame, k: int) -> dict[str, float]:
    """Walk forward week by week. Each week ranks only that week's scores, which use data up to that week (cusum
    looks back only, gi and midp are per week), so no week reads a later one."""
    weeks = sorted(rows["date"].unique())
    hits, flagged, positives, first_pos, first_hit = 0, 0, 0, None, None
    precisions, false_alerts = [], []
    for i, d in enumerate(weeks):
        w = rows[rows["date"] == d]
        top = _topk(w, agent, k)
        tp = int(w.loc[top, "label"].sum())
        pos = int(w["label"].sum())
        precisions.append(tp / len(top) if len(top) else np.nan)
        false_alerts.append(len(top) - tp)
        hits, flagged, positives = hits + tp, flagged + len(top), positives + pos
        if pos and first_pos is None:
            first_pos = i
        if tp and first_hit is None:
            first_hit = i
    return {
        "precision_at_k": float(np.nanmean(precisions)) if precisions else np.nan,
        "recall": hits / positives if positives else np.nan,
        "weeks_to_detect": float(first_hit - first_pos)
        if first_hit is not None and first_pos is not None
        else np.nan,
        "false_alerts_per_week": float(np.mean(false_alerts)) if false_alerts else np.nan,
    }


def backtest_agent(name: str, regime: str, seeds: Sequence[int]) -> pd.DataFrame:
    """One row per seed: precision@k (k = learn.alert_budget), recall of planted cell-weeks, weeks from the first
    drop to the agent's first hit, and false alerts per week (top-k cells with no drop)."""
    if name not in AGENTS:
        raise ValueError(f"unknown agent {name!r}; one of {AGENTS}")
    k = int(load(io.CONFIG_PATH)[0]["learn"]["alert_budget"])
    rows = [
        {"agent": name, "regime": regime, "seed": s, **_one(name, _season(regime, s), k)}
        for s in seeds
    ]
    return pd.DataFrame(rows, columns=BACKTEST_COLUMNS)


def overlap(seeds: Sequence[int], regime: str = "fixed") -> tuple[pd.DataFrame, pd.DataFrame]:
    """(kappa, rho): pairwise Cohen's kappa of weekly top-k flags and Spearman rho of scores, pooled over seeds."""
    k = int(load(io.CONFIG_PATH)[0]["learn"]["alert_budget"])
    rows = pd.concat([_season(regime, s) for s in seeds], ignore_index=True)
    flags = pd.DataFrame(False, index=rows.index, columns=list(AGENTS))
    for _, w in rows.groupby(["seed", "date"]):
        for a in AGENTS:
            flags.loc[_topk(w, a, k), a] = True
    kap = pd.DataFrame(1.0, index=list(AGENTS), columns=list(AGENTS))
    rho = kap.copy()
    for i, a in enumerate(AGENTS):
        for b in AGENTS[i + 1 :]:
            kab = kappa(flags[a], flags[b])
            r = spearmanr(rows[a], rows[b]).statistic
            kap.loc[a, b] = kap.loc[b, a] = float(kab)
            rho.loc[a, b] = rho.loc[b, a] = float(r)
    return kap, rho


def merge(kap: pd.DataFrame, threshold: float, precision: Mapping[str, float]) -> list[list[str]]:
    """Groups of agents linked by kappa >= threshold (transitively); each group best-first by precision@k."""
    parent = {a: a for a in kap.index}

    def root(a: str) -> str:
        while parent[a] != a:
            a = parent[a]
        return a

    for a in kap.index:
        for b in kap.columns:
            if a != b and kap.loc[a, b] >= threshold:
                parent[root(b)] = root(a)
    groups: dict[str, list[str]] = {}
    for a in kap.index:
        groups.setdefault(root(a), []).append(a)
    best = lambda g: sorted(
        g, key=lambda a: (-np.nan_to_num(precision.get(a, np.nan), nan=-1.0), a)
    )
    return sorted((best(g) for g in groups.values()), key=lambda g: g[0])


def null_samples(seeds: Sequence[int]) -> dict[str, list[float]]:
    """Per agent, sorted scores from `null`-regime seasons (no drops), at most NULL_MAX, evenly thinned."""
    rows = pd.concat([_season("null", s) for s in seeds], ignore_index=True)
    out = {}
    for a in AGENTS:
        v = np.sort(rows[a].dropna().to_numpy(float))
        if len(v) > NULL_MAX:
            v = v[np.linspace(0, len(v) - 1, NULL_MAX).round().astype(int)]
        out[a] = [float(x) for x in v]
    return out


def _null_or_empty(seeds: Sequence[int]) -> dict[str, list[float]]:
    try:
        return null_samples(seeds)
    except NotImplementedError:
        log.warning(
            "no `null` regime in the simulator yet (#150): no null samples, fuse keeps p_comb = p_perm"
        )
        return {}


def write_signals_report(seeds: Sequence[int] | None = None) -> Path:
    """reports/signals.json: metrics per agent and regime, kappa and rho, merged groups and null samples."""
    cfg, sha = load(io.CONFIG_PATH)
    learn = cfg["learn"]
    seeds = list(seeds if seeds is not None else range(int(learn["n_seeds_quick"])))
    regimes = []
    for r in [*learn["regimes"]["train"], *learn["regimes"]["held_out"]]:
        try:
            _season(r, seeds[0])
            regimes.append(r)
        except NotImplementedError:  # the simulator doesn't have this regime yet (#150)
            log.warning("regime %r not in the simulator yet: skipped", r)
    bt = pd.concat(
        [backtest_agent(a, r, seeds) for a in AGENTS for r in regimes], ignore_index=True
    )
    held = bt[
        bt["regime"].isin(learn["regimes"]["held_out"])
    ]  # merge order: held-out precision (L2 step 3)
    precision = held.groupby("agent")["precision_at_k"].mean().to_dict()
    kap, rho = overlap(seeds)
    agents: dict[str, Any] = {
        a: {
            r: g.drop(columns=["agent", "regime", "seed"]).mean().to_dict()
            for r, g in bt[bt["agent"] == a].groupby("regime")
        }
        for a in AGENTS
    }
    out = {
        "agents": agents,
        "kappa": kap.to_dict(),
        "rho": rho.to_dict(),
        "merged": merge(kap, float(learn["merge_kappa"]), precision),
        "null": _null_or_empty(seeds),
        "seeds": seeds,
        "regimes": regimes,
        "config_hash": sha,
    }
    path = Path(os.environ.get("NARCO_REPORTS", io.ROOT / "reports")) / "signals.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(train._plain(out), indent=1, allow_nan=False))  # NaN -> null
    return path
