"""Private: P6 parameters and the provenance of an input stage file."""

import json
import logging
import os
from pathlib import Path

import pyarrow.parquet as pq

from core import io
from core.config import load

log = logging.getLogger(__name__)

# TODO(P1): add these keys to config.yaml under `p6` (#123). Values are docs/specs/P6.md, Parameters, plus rho from A1.
# cusum_h: 0.5 is the fallback pick (question #124). D2 (#174): make validate fits h on null simulator runs so a quiet
# cell (mu = sim.slowdown_rate_cold) alarms once per p6.cusum_alarm_days (A1: about once a quarter) and writes
# reports/cusum_h.json; _fitted_h() uses it while its config_hash matches.
_SPEC = {
    "fdr_q": 0.1,
    "gi_band_m": 2900,
    "gi_perm": 999,
    "cusum_rho": 2,
    "cusum_h": 0.5,
    "top_frac": 0.1,
    # context facts (docs/specs/P6.md step 4; slow hours from shared.md issue 3). TODO(P1): config keys, #123
    "inshore_max": 0.1,
    "coast_min_m": 2000,
    "coast_max_m": 25000,
    "slow_hours_min": 0.33,
    "slow_hours_max": 3,
}
PARAMS = {**_SPEC, **load(io.CONFIG_PATH)[0].get("p6", {})}


def _fitted_h() -> float | None:
    """D2 (#174): h fitted on null simulator runs (validate/cusum.py), if reports/cusum_h.json matches the config."""
    path = Path(os.environ.get("NARCO_REPORTS", io.ROOT / "reports")) / "cusum_h.json"
    try:
        body = json.loads(path.read_text()) if path.exists() else None
    except (OSError, ValueError):
        body = None
    if not body or body.get("config_hash") != load(io.CONFIG_PATH)[1] or body.get("h") is None:
        log.info(
            "no fitted h in reports/cusum_h.json: cusum_h = %s (picked; D2)", PARAMS["cusum_h"]
        )
        return None
    return float(body["h"])


_h = _fitted_h()
if _h is not None:
    PARAMS["cusum_h"] = _h


def _provenance(name: str) -> str:
    """'simulated' or 'real', read from the stamp core.io wrote on a parquet stage file."""
    meta = pq.read_schema(io.stage_path(name)).metadata or {}
    return json.loads(meta[b"narco"])["provenance"]
