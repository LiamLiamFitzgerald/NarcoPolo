"""Stack and challenger ladder, fitted on the simulator (docs/learning.md L4). PLACEHOLDER: always rung 0 until #154."""

import json
import os
from pathlib import Path
from typing import Any

from core import io
from core.config import load


def model_path() -> Path:
    """Shared with fuse.learn (P6): <data root>/models/site_model.json."""
    return Path(os.environ.get("NARCO_DATA", io.ROOT / "data")) / "models" / "site_model.json"


def fit_site_model(regimes: list[str], seeds: list[int]) -> dict[str, Any]:
    """Writes the model file fuse.learn.site_value reads. Rung 0 = the statistics alone (p_site from p_comb)."""
    cfg, config_hash = load(io.CONFIG_PATH)
    model = {
        "rung": 0,  # TODO(P1) #154: rung 1 stack, rung 2 NAM, promotion rule, ablation
        "features": list(cfg["learn"]["agents"]),
        "weights": [],
        "intercept": 0.0,
        "config_hash": config_hash,
        "metrics": {},
        "seeds": list(seeds),
        "regimes": list(regimes),
    }
    path = model_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, indent=1))
    return model
