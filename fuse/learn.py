"""L4 apply side (docs/learning.md): p_site from the site model P1 fitted on the simulator, rung 0 fallback."""

import json
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core import io
from core.config import load
from fuse import combine

log = logging.getLogger(__name__)


def model_path() -> Path:
    """Shared with validate/train.py (#154): <data root>/models/site_model.json."""
    return Path(os.environ.get("NARCO_DATA", io.ROOT / "data")) / "models" / "site_model.json"


def load_model() -> dict[str, Any] | None:
    """The site model, or None (logged) when it is missing, unreadable or fitted under another config."""
    path = model_path()
    if not path.exists():
        log.info("no site model at %s: rung 0 (statistics only)", path)
        return None
    try:
        model = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        log.warning("site model unreadable (%s): rung 0", e)
        return None
    if not isinstance(model, dict) or model.get("config_hash") != load(io.CONFIG_PATH)[1]:
        log.warning("site model config_hash is stale: rung 0")
        return None
    return model


def _rung0(sites: pd.DataFrame) -> pd.Series:
    """The statistics alone: p_site = percentile rank of 1 - p_comb (ties share the average rank)."""
    return (1 - sites["p_comb"]).rank(pct=True).rename("p_site")


def _rung1(sites: pd.DataFrame, model: dict[str, Any]) -> pd.Series | None:
    """Monotone logistic stack: sigmoid(intercept + sum w_f x_f), every w_f >= 0. None if it can't be applied."""
    try:
        features = list(model["features"])
        w = np.asarray(model["weights"], float)
        b = float(model["intercept"])
    except (KeyError, TypeError, ValueError):
        log.warning("rung 1 model lacks features/weights/intercept: rung 0")
        return None
    if len(w) != len(features) or not np.all(np.isfinite(w)) or np.any(w < 0):
        log.warning("rung 1 weights must be finite, >= 0 and one per feature: rung 0")
        return None
    missing = [f for f in features if f not in sites.columns]
    if missing:
        log.warning("rung 1 features %s not on the sites: rung 0", missing)
        return None
    x = sites[features].to_numpy(float)
    if not np.all(np.isfinite(x)):
        log.warning("rung 1 features have missing values: rung 0")
        return None
    return pd.Series(1 / (1 + np.exp(-(b + x @ w))), index=sites.index, name="p_site")


def _site_value(sites: pd.DataFrame, model: dict[str, Any] | None) -> tuple[pd.Series, int]:
    rung = int(model.get("rung", 0)) if model else 0
    if rung == 1 and model is not None:
        p = _rung1(sites, model)
        if p is not None:
            return p, 1
    elif (
        rung > 1
    ):  # neural / tree / gated rungs need site_model.pt and a runtime fuse does not have yet
        log.warning("site model rung %d is not applied in fuse yet: rung 0", rung)
    return _rung0(sites), 0


def site_value(sites: pd.DataFrame, model: dict[str, Any] | None) -> pd.Series:
    """p_site in 0-1 per site. Any model that is missing, stale or can't be applied gives rung 0, never a crash.
    The rung actually used is in .attrs["rung"]."""
    p, rung = _site_value(sites, model)
    p.attrs["rung"] = rung
    return p


def _agent_pvalues(sites: pd.DataFrame, agents) -> pd.DataFrame:
    """One-sided p per agent per site. link = p_perm (the lag-link permutation p). Any other agent: its p_<agent>
    column if the working frame has one, else its score_<agent> (higher = more unusual) against the agent's
    null-regime samples in reports/signals.json (#164). Agents with neither are left out, not given p = 1."""
    null = combine.signals().get("null") or {}
    cols = {"link": sites["p_perm"]} if "link" in agents else {}
    for a in agents:
        if a == "link":
            continue
        if f"p_{a}" in sites.columns:
            cols[a] = sites[f"p_{a}"]
        elif f"score_{a}" in sites.columns and len(null.get(a) or []):
            cols[a] = combine.null_pvalue(sites[f"score_{a}"], null[a])
    return pd.DataFrame(cols, index=sites.index)


def _add_learning_columns(sites: pd.DataFrame, q: float) -> pd.DataFrame:
    """fuse/sites + p_comb, comb_flag, agreement_merged, p_site, model_rung on every row. Agent scores (-log10 p,
    named by agent) are offered to the site model and not written (the fuse/sites schema is strict)."""
    merged = combine.groups()
    pv = _agent_pvalues(sites, [a for g in merged for a in g])
    p_comb = combine.cct(pv, combine.weights(pv.columns, merged))
    if p_comb.isna().any():  # no agent p at all: "no evidence" (p = 1), never "unusual"
        log.warning("%d sites have no agent p value: p_comb = 1", int(p_comb.isna().sum()))
        p_comb = p_comb.fillna(1.0)
    model = load_model()
    t = model.get("p_comb_threshold") if model else None
    threshold = float(t) if t is not None else None
    out = sites.assign(
        p_comb=p_comb,
        comb_flag=combine.flags(p_comb, q, threshold),
        agreement_merged=combine.agreement_merged(pv, merged, q),
    )
    scores = -np.log10(pv.clip(lower=np.finfo(float).tiny))
    p_site, rung = _site_value(
        pd.concat([out, scores.drop(columns=out.columns, errors="ignore")], axis=1), model
    )
    return out.assign(p_site=p_site.astype(float), model_rung=rung)
