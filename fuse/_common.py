"""Private: P6 parameters and the provenance of an input stage file (tach forbids importing detectors/)."""

import json

import pyarrow.parquet as pq

from core import io
from core.config import load

# TODO(P1): add these keys to config.yaml under `p6`. Values are docs/specs/P6.md, Parameters.
_SPEC = {
    "fdr_q": 0.1, "link_radius_m": 4000, "link_days": 7, "tau_days": 3, "half_life_days": 30,
    "shift_days": 60, "n_shuffles": 999, "pier_tau_h": 1,
}  # fmt: skip
PARAMS = {**_SPEC, **load(io.CONFIG_PATH)[0].get("p6", {})}


def _provenance(name: str) -> str:
    """'simulated' or 'real', read from the stamp core.io wrote on a parquet stage file."""
    meta = pq.read_schema(io.stage_path(name)).metadata or {}
    return json.loads(meta[b"narco"])["provenance"]
