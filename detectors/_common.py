"""Private: P6 parameters and the provenance of an input stage file."""

import json

import pyarrow.parquet as pq

from core import io
from core.config import load

# TODO(P1): add these keys to config.yaml under `p6` (#123). Values are docs/specs/P6.md, Parameters, plus rho from A1.
# TODO(P6): cusum_h is not in the spec (#124). D2: the smallest h with <= cusum_alarms_per_quarter alarms per
# observed cell-quarter on null-regime simulator runs (scores._calibrate_h): 0.50 on seed 1, 0.53 on seed 2, so 0.5
# stays. test_cusum_h_is_calibrated_on_a_null_simulator_run checks it.
_SPEC = {
    "fdr_q": 0.1,
    "gi_band_m": 2900,
    "cusum_rho": 2,
    "cusum_h": 0.5,
    "cusum_alarms_per_quarter": 1.0,  # TODO(P6): D2 target false-alarm rate per cell on null runs (#124)
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
