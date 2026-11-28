"""L3 (docs/learning.md): Cauchy-combined p per site, calibrated on null runs, BH -> comb_flag, merged agreement."""

import json
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

from core import io
from core.config import load

log = logging.getLogger(__name__)


def _bh(p: np.ndarray, q: float) -> np.ndarray:
    """Benjamini-Hochberg once over the whole set (fuse may not import detectors/, so not detectors.bh)."""
    return multipletests(p, alpha=q, method="fdr_bh")[0] if len(p) else np.zeros(0, bool)


def signals() -> dict:
    """reports/signals.json written by L2 (validate.signals, #153), or {} before it exists or if unreadable."""
    path = Path(os.environ.get("NARCO_REPORTS", io.ROOT / "reports")) / "signals.json"
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError) as e:
        log.warning("reports/signals.json unreadable (%s): agents unmerged, no null samples", e)
        return {}


def groups() -> list[list[str]]:
    """Merged agents: reports/signals.json "merged" once L2 has written it, else one group per learn.agents."""
    merged = signals().get("merged")
    if merged:
        return [list(g) for g in merged]
    return [[a] for a in load(io.CONFIG_PATH)[0]["learn"]["agents"]]


def null_pvalue(scores: pd.Series, null) -> pd.Series:
    """Site-level p of an agent score against its null-regime samples (#164): (1 + #null >= score) / (1 + n).
    Never 0, so an extreme score is "rarer than every null sample", not impossible. NaN score stays NaN."""
    ref = np.sort(np.asarray(null, float))
    s = scores.to_numpy(float)
    ge = len(ref) - np.searchsorted(ref, s, side="left")  # null samples >= score
    p = np.where(np.isfinite(s), (1 + ge) / (1 + len(ref)), np.nan)
    return pd.Series(p, index=scores.index, name=scores.name)


def attention() -> dict[str, float] | None:
    """Regret weight per merged group from reports/attention.json (L6, docs/learning.md L3 step 4a), keyed by the
    group's agents joined with "+" (e.g. "oe+midp"). None, logged, when it is missing, unreadable or fitted under
    another config: then every group votes equally."""
    path = Path(os.environ.get("NARCO_REPORTS", io.ROOT / "reports")) / "attention.json"
    if not path.exists():
        log.info("no reports/attention.json: equal votes per merged group")
        return None
    try:
        body = json.loads(path.read_text())
        if body.get("config_hash") != load(io.CONFIG_PATH)[1]:
            log.warning("reports/attention.json config_hash is stale: equal votes per merged group")
            return None
        return {g: float(v["weight"]) for g, v in body["groups"].items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        log.warning("reports/attention.json unreadable (%s): equal votes per merged group", e)
        return None


def weights(columns, merged: list[list[str]]) -> pd.Series:
    """CCT weight per agent. Each merged group gets its regret weight from attention() (a group the file does not
    list gets learn.attention_floor), or 1 when there is no file; group weights are renormalised over the groups
    with a column and split equally over the group's agents present, so three agents driven by the same counts
    share one vote. Weights are fixed from simulator backtests before they are applied (L3 4a), so CCT stays valid."""
    present = [[a for a in g if a in columns] for g in merged]
    keyed = [("+".join(g), p) for g, p in zip(merged, present, strict=True) if p]
    att = attention()
    floor = float(load(io.CONFIG_PATH)[0]["learn"]["attention_floor"]) if att is not None else 1.0
    gw = {k: (att.get(k, floor) if att is not None else 1.0) for k, _ in keyed}
    total = sum(gw.values())
    w = {a: gw[k] / total / len(p) for k, p in keyed for a in p} if total > 0 else {}
    return pd.Series(w, dtype=float)


def cct(pvalues: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Cauchy combination (Liu & Xie 2020): T = sum w_i tan((0.5 - p_i) pi), p = 0.5 - arctan(T) / pi.
    NaN p (agent not available for that row) leave the row's sum and its weights are renormalised to 1."""
    w = weights.reindex(pvalues.columns).fillna(0.0).to_numpy(float)
    p = pvalues.to_numpy(float)
    # p = 0 or 1 make tan infinite; clip to the float range so the result stays in [0, 1] and monotone
    eps = np.finfo(float).eps
    t = np.tan((0.5 - np.clip(p, eps, 1 - eps)) * np.pi)
    ok = np.isfinite(p)
    W = np.where(ok, w, 0.0)
    total = W.sum(axis=1)
    T = np.where(ok, W * t, 0.0).sum(axis=1) / np.where(total > 0, total, 1.0)
    out = np.where(total > 0, 0.5 - np.arctan(T) / np.pi, np.nan)
    return pd.Series(np.clip(out, 0.0, 1.0), index=pvalues.index, name="p_comb")


def calibrate(null_pcomb: pd.Series, target: float) -> float:
    """Threshold t so that p_comb <= t gives `target` false alerts per week on null runs (CCT is
    anti-conservative under positive correlation, so the nominal level is not trusted).
    null_pcomb: p values from null runs; the first index level is the week (any label; run and week together
    if several runs). Returns 0.0 when the target allows no alert at all."""
    p = np.sort(null_pcomb.dropna().to_numpy(float))
    n_weeks = null_pcomb.index.get_level_values(0).nunique()
    k = int(np.floor(target * n_weeks))
    if k <= 0 or not len(p):
        return 0.0
    return float(p[min(k, len(p)) - 1])


def flags(p_comb: pd.Series, q: float, threshold: float | None = None) -> pd.Series:
    """comb_flag: BH at q across sites; with a calibrated threshold also p_comb <= threshold."""
    f = _bh(p_comb.to_numpy(float), q)
    if threshold is not None:
        f &= p_comb.to_numpy(float) <= threshold
    return pd.Series(f, index=p_comb.index, name="comb_flag")


def agreement_merged(pvalues: pd.DataFrame, merged: list[list[str]], q: float) -> pd.Series:
    """Number of merged groups whose own p (CCT within the group) is BH-significant at q across sites."""
    n = pd.Series(0, index=pvalues.index, name="agreement_merged", dtype=int)
    for g in merged:
        cols = [a for a in g if a in pvalues.columns]
        if not cols:
            continue
        pg = cct(pvalues[cols], pd.Series(1 / len(cols), index=cols))
        ok = pg.notna().to_numpy()
        hit = np.zeros(len(pg), bool)
        hit[ok] = _bh(pg.to_numpy(float)[ok], q)
        n += hit.astype(int)
    return n
