"""Private: P6 parameters and the provenance of an input stage file."""

import json

import pyarrow.parquet as pq

from core import io
from core.config import load

# TODO(P1): add these keys to config.yaml under `p6`. Values are docs/specs/P6.md, Parameters, plus rho from A1.
# cusum_h is None because A1 says to choose it on the simulator null; the spec gives no value.
_SPEC = {
    "fdr_q": 0.1,
    "gi_band_m": 2900,
    "gi_perm": 999,
    "cusum_rho": 2,
    "cusum_h": None,
    "top_frac": 0.1,
}
PARAMS = {**_SPEC, **load(io.CONFIG_PATH)[0].get("p6", {})}


def _provenance(name: str) -> str:
    """'simulated' or 'real', read from the stamp core.io wrote on a parquet stage file."""
    meta = pq.read_schema(io.stage_path(name)).metadata or {}
    return json.loads(meta[b"narco"])["provenance"]
