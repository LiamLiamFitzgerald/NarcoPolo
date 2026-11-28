"""D2 (#174): fit the CUSUM threshold h on null-regime simulator runs (A1) and write reports/cusum_h.json, which
detectors read in place of the picked 0.5 while its config_hash matches."""

import json
import os
from pathlib import Path

from core import io
from core.config import load
from detectors._common import PARAMS
from detectors.scores import _alarm_rate, _calibrate_h
from validate.train import _scratch, _simulate


def _quiet_series(cfg, seed: int) -> list:
    """(C, mu, phi) per quiet slowdown cell (mu = sim.slowdown_rate_cold) on one null-regime season, observed
    days only, in date order: the series A1 sets h on."""
    with _scratch():
        _simulate(cfg, seed, "null")
        obs = io.read_stage("aggregate/observed")
        exp = io.read_stage("forecast/expected")
    key = ["cell_id", "date", "event_type"]
    m = obs[obs["exposure"] > 0].merge(exp[exp["fold"].fillna(0) == 0], on=key)
    quiet = m[(m["event_type"] == "slowdown") & (m["mu"] == cfg["sim"]["slowdown_rate_cold"])]
    return [
        (g["count"].to_numpy(), g["mu"].to_numpy(), g["phi"].to_numpy())
        for _, g in quiet.sort_values("date").groupby("cell_id")
    ]


def report_path() -> Path:
    return Path(os.environ.get("NARCO_REPORTS", io.ROOT / "reports")) / "cusum_h.json"


def write_cusum_report(seeds=None) -> dict:
    """Fit h over n_seeds_quick null seasons pooled, and write it with what it was fitted on."""
    cfg, config_hash = load(io.CONFIG_PATH)
    seeds = list(range(int(cfg["learn"]["n_seeds_quick"]))) if seeds is None else list(seeds)
    series = [s for seed in seeds for s in _quiet_series(cfg, seed)]
    per_days = float(cfg["p6"]["cusum_alarm_days"])
    fitted = _calibrate_h(series, per_days)
    h = (
        PARAMS["cusum_h"] if fitted is None else fitted
    )  # target not binding: keep the pick, report that it passes
    body = {
        "h": fitted,  # None = the target does not constrain h on these runs; detectors keep their h
        "h_checked": h,
        "binding": fitted is not None,
        "alarm_days_target": per_days,
        "alarms_per_91_days": _alarm_rate(series, h) * 91,
        "regime": "null",
        "seeds": seeds,
        "quiet_cells": len(series),
        "config_hash": config_hash,
    }
    path = report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2))
    return body
