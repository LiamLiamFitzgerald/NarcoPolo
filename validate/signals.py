"""Per-signal agents and their backtests (docs/learning.md L2). PLACEHOLDER: interfaces only; built in issue #153."""

import json
import os
from pathlib import Path

import pandas as pd

from core import io
from core.config import load

AGENTS = ("oe", "midp", "gi", "cusum", "link")
BACKTEST_COLUMNS = [
    "agent",
    "regime",
    "seed",
    "precision_at_k",
    "recall",
    "weeks_to_detect",
    "false_alerts_per_week",
]


def backtest_agent(name: str, regime: str, seeds: list[int]) -> pd.DataFrame:
    if name not in AGENTS:
        raise ValueError(f"unknown agent {name!r}; one of {AGENTS}")
    return pd.DataFrame(columns=BACKTEST_COLUMNS)  # TODO(P1) #153: walk-forward, one agent alone


def overlap(seeds: list[int]) -> pd.DataFrame:
    """Pairwise Cohen's kappa of top-k flags (placeholder: identity, i.e. no agent merged)."""
    return pd.DataFrame(
        [[1.0 if a == b else 0.0 for b in AGENTS] for a in AGENTS],
        index=list(AGENTS),
        columns=list(AGENTS),
    )  # TODO(P1) #153


def write_signals_report(seeds: list[int]) -> Path:
    """reports/signals.json: per-agent metrics, kappa matrix and the merged groups that L3 (fuse) reads."""
    cfg, _ = load(io.CONFIG_PATH)
    k = overlap(seeds)
    merged = [[a] for a in cfg["learn"]["agents"]]  # placeholder: every agent alone until #153
    out = {"agents": {}, "kappa": k.to_dict(), "merged": merged, "placeholder": True}
    path = Path(os.environ.get("NARCO_REPORTS", io.ROOT / "reports")) / "signals.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    return path
