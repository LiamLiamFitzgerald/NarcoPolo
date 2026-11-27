"""Private: P6 parameters and the provenance of an input stage file."""

import json

import pyarrow.parquet as pq

from core import io
from core.config import load

# TODO(P1): add these keys to config.yaml under `p6` (#123). Values are docs/specs/P6.md, Parameters, plus rho from A1.
# TODO(P6): cusum_h is not in the spec (question #124). A1: chosen on the simulator null so a quiet cell (mu = sim
# slowdown_rate_cold) alarms about once a quarter; test_cusum_alarms_about_once_a_quarter_on_quiet_simulator_cells
# checks it. Any h below ln(rho) - mu gives that rate (one event alarms), so 0.5 is a pick, not a fit.
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


def _provenance(name: str) -> str:
    """'simulated' or 'real', read from the stamp core.io wrote on a parquet stage file."""
    meta = pq.read_schema(io.stage_path(name)).metadata or {}
    return json.loads(meta[b"narco"])["provenance"]
