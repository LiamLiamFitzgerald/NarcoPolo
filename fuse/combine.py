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


def groups() -> list[list[str]]:
    """Merged agents: reports/signals.json "merged" once L2 has written it, else one group per learn.agents."""
    path = Path(os.environ.get("NARCO_REPORTS", io.ROOT / "reports")) / "signals.json"
    if path.exists():
        merged = json.loads(path.read_text()).get("merged")
        if merged:
            return [list(g) for g in merged]
    return [[a] for a in load(io.CONFIG_PATH)[0]["learn"]["agents"]]


def weights(columns, merged: list[list[str]]) -> pd.Series:
    """Equal weight 1/m per merged group, split equally over the group's agents that have a column, so three
    agents driven by the same counts carry one vote, not three. Groups with no column drop out of m."""
    present = [[a for a in g if a in columns] for g in merged]
    present = [g for g in present if g]
    w = {a: 1 / (len(present) * len(g)) for g in present for a in g}
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
