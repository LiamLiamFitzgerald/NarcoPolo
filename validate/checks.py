"""Independent checks on our numbers. Reads the simulator truth; never tunes a module's thresholds."""

import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core import io
from core.config import load
from validate.backtest import backtest
from validate.injection import injection_test
from validate.null import null_test

LENGTH_BINS = [("<8", 0, 8), ("8-12", 8, 12), ("12-15", 12, 15), ("15-24", 15, 24)]
KEYS = ("recall", "injection", "skill", "calibration", "brier", "null")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p, z2 = k / n, z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def _within(truth_xy: np.ndarray, det_xy: np.ndarray, metres: float) -> np.ndarray:
    """For each truth point, is any detection within `metres`?"""
    if len(truth_xy) == 0 or len(det_xy) == 0:
        return np.zeros(len(truth_xy), bool)
    d = np.hypot(
        truth_xy[:, None, 0] - det_xy[None, :, 0], truth_xy[:, None, 1] - det_xy[None, :, 1]
    )
    return (d <= metres).any(axis=1)


def recall_curve(
    detections: pd.DataFrame, truth: pd.DataFrame, calm_by_pass: Mapping[str, bool]
) -> pd.DataFrame:
    """Recall of true boats inside a pass footprint: detected = a non-ghost detection of that pass within 300 m."""
    boats = truth[
        (truth["kind"] != "drop") & (truth["pass_index"] >= 0) & (truth["length_m"] < 24)
    ].copy()
    boats["pass_id"] = [f"pass_{i:03d}" for i in boats["pass_index"]]
    boats["hit"] = False
    real = detections[~detections["ghost"]]
    for pid, grp in boats.groupby("pass_id"):
        d = real[real["pass_id"] == pid]
        boats.loc[grp.index, "hit"] = _within(
            grp[["x_m", "y_m"]].to_numpy(), d[["x_m", "y_m"]].to_numpy(), 300.0
        )
    boats["sea_state"] = ["calm" if calm_by_pass[p] else "rough" for p in boats["pass_id"]]
    rows = []
    for label, lo, hi in LENGTH_BINS:
        for state in ("calm", "rough"):
            g = boats[
                (boats["length_m"] >= lo) & (boats["length_m"] < hi) & (boats["sea_state"] == state)
            ]
            k, n = int(g["hit"].sum()), len(g)
            lo_, hi_ = wilson(k, n)
            rows.append(
                {
                    "length_bin": label,
                    "sea_state": state,
                    "n": n,
                    "detected": k,
                    "recall": k / n if n else None,
                    "lo": lo_,
                    "hi": hi_,
                }
            )
    return pd.DataFrame(rows)


def calibration(
    pred: np.ndarray, outcome: np.ndarray, bins: int = 10, min_n: int = 20
) -> tuple[pd.DataFrame, float]:
    """Reliability table and Brier score. A bin with fewer than min_n rows is merged into the next one."""
    pred, outcome = np.asarray(pred, float), np.asarray(outcome, float)
    idx = np.minimum((pred * bins).astype(int), bins - 1)
    raw = [
        (
            b / bins,
            (b + 1) / bins,
            int((idx == b).sum()),
            pred[idx == b].sum(),
            outcome[idx == b].sum(),
        )
        for b in range(bins)
    ]
    merged: list[list[float]] = []
    carry: list[float] | None = None
    for lo, hi, n, sp, so in raw:
        if n == 0 and carry is None:
            continue
        cur = (
            [lo, hi, n, sp, so]
            if carry is None
            else [carry[0], hi, carry[2] + n, carry[3] + sp, carry[4] + so]
        )
        carry = None if cur[2] >= min_n else cur
        if carry is None:
            merged.append(cur)
    if carry is not None:  # a short tail joins the previous bin
        if merged:
            prev = merged[-1]
            merged[-1] = [
                prev[0],
                carry[1],
                prev[2] + carry[2],
                prev[3] + carry[3],
                prev[4] + carry[4],
            ]
        else:
            merged.append(carry)
    table = pd.DataFrame(
        [
            {
                "bin_lo": b[0],
                "bin_hi": b[1],
                "n": int(b[2]),
                "mean_pred": b[3] / b[2],
                "observed": b[4] / b[2],
            }
            for b in merged
            if b[2] > 0
        ]
    )
    return table, float(np.mean((pred - outcome) ** 2)) if len(pred) else float("nan")


def interval_coverage(expected: pd.DataFrame, observed: pd.DataFrame) -> float:
    """Share of observed rows (exposure > 0) whose count is inside [lo90, hi90]; the target is about 0.9 (A14)."""
    m = observed[observed["exposure"] > 0].merge(expected, on=["cell_id", "date", "event_type"])
    return (
        float(((m["count"] >= m["lo90"]) & (m["count"] <= m["hi90"])).mean())
        if len(m)
        else float("nan")
    )


def simulator_recovery() -> dict[str, Any]:
    """Planted site rank (by S, within 3 km of a true drop) and observed / expected ratio per event type (target 0.8-1.2)."""
    truth = pd.read_parquet(io.truth_path())
    drop = truth[truth["kind"] == "drop"].iloc[0]
    sites = io.read_stage("fuse/sites").sort_values("S", ascending=False).reset_index(drop=True)
    near = np.hypot(sites["x_m"] - drop["x_m"], sites["y_m"] - drop["y_m"]) <= 3000
    obs = io.read_stage("aggregate/observed")
    exp = io.read_stage("forecast/expected")
    m = obs[(obs["level"] == 2000) & (obs["exposure"] > 0)].merge(
        exp, on=["cell_id", "date", "event_type"]
    )
    ratio = (m.groupby("event_type")["count"].sum() / m.groupby("event_type")["mu"].sum()).to_dict()
    return {
        "planted_site_rank": int(near.idxmax()) + 1 if near.any() else None,
        "observed_over_expected": ratio,
    }


def _clean(x: Any) -> Any:
    if isinstance(x, pd.DataFrame):
        return _clean(x.to_dict("records"))
    if isinstance(x, Mapping):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_clean(v) for v in x]
    if isinstance(x, np.generic):
        return _clean(x.item())
    return None if isinstance(x, float) and math.isnan(x) else x


def _injection() -> pd.DataFrame:
    """injection_test on the first chips in raw/s1, with the levels and counts from config `validate:`."""
    cfg, _ = load(io.CONFIG_PATH)
    v = cfg["validate"]
    ids = sorted(p.stem for p in (io.raw_root() / "s1").glob("*.json"))[: v["injection_passes"]]
    return injection_test(
        ids, list(v["injection_brightness_db"]), v["injection_n_per_pass"], cfg["seed"]
    )


def write_report(results: Mapping[str, Any]) -> Path:
    """reports/validation.json with the keys P7 reads; a missing key becomes an empty result."""
    out = {
        k: results.get(
            k,
            {"runs": 0, "share_with_any_flag": None}
            if k == "null"
            else None
            if k == "brier"
            else [],
        )
        for k in KEYS
    }
    out |= {
        k: v for k, v in results.items() if k not in KEYS
    }  # extra results (interval coverage, recovery) ride along
    path = Path(os.environ.get("NARCO_REPORTS", io.ROOT / "reports")) / "validation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(out), indent=1, allow_nan=False))
    return path


def run() -> Path:
    """make validate on the simulator: recall, p_boat calibration, interval coverage and recovery."""
    det = io.read_stage("detect/detections")
    truth = pd.read_parquet(io.truth_path())
    exposure = io.read_stage("coverage/exposure")
    calm = exposure.groupby("pass_id")["calm"].first().to_dict()
    recall = recall_curve(det, truth, calm)
    real = det[~det["ghost"]]
    boats = truth[(truth["kind"] != "drop") & (truth["pass_index"] >= 0)].assign(
        pass_id=lambda t: [f"pass_{i:03d}" for i in t["pass_index"]]
    )
    outcome = np.zeros(len(real), bool)
    for pid, grp in real.groupby("pass_id"):
        b = boats[boats["pass_id"] == pid]
        outcome[real.index.get_indexer(grp.index)] = _within(
            grp[["x_m", "y_m"]].to_numpy(), b[["x_m", "y_m"]].to_numpy(), 300.0
        )
    table, brier = calibration(real["p_boat"].to_numpy(), outcome)
    coverage = interval_coverage(
        io.read_stage("forecast/expected"), io.read_stage("aggregate/observed")
    )
    return write_report(
        {
            "recall": recall,
            "calibration": table,
            "brier": brier,
            "interval_coverage": coverage,
            "recovery": simulator_recovery(),
            "injection": _injection(),
            "null": null_test(),
            "skill": pd.concat([backtest("slowdown"), backtest("dark_small")], ignore_index=True),
        }
    )
