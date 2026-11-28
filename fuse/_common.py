"""Private: P6 parameters and the provenance of an input stage file (tach forbids importing detectors/)."""

import json

import pyarrow.parquet as pq

from core import io
from core.config import load

# TODO(P1): add these keys to config.yaml under `p6` (#123). Values are docs/specs/P6.md, Parameters.
_SPEC = {
    "fdr_q": 0.1, "top_frac": 0.1, "inshore_max": 0.1, "link_radius_m": 4000, "link_days": 7, "tau_days": 3, "half_life_days": 30,
    "shift_days": 60, "n_shuffles": 999, "pier_tau_h": 1,
    "site_flags": True,  # the spec flags sites by BH over p_perm; config can switch it off (#269)
    "test_top_k": 15,  # #177: BH over the top-k sites by S only (= patrol.top_sites, the patrol candidates)
    "perm_seed_offset": 60,  # TODO(P1): per-use seed offset for the site permutation test (global seed + this)
}  # fmt: skip
_CFG = load(io.CONFIG_PATH)[0]
PARAMS = {**_SPEC, **_CFG.get("p6", {})}
RADAR_HISTORY_DAYS = int(_CFG["radar_history_days"])  # T - 89 .. T (shared.md, Global settings)


def _provenance(name: str) -> str:
    """'simulated' or 'real', read from the stamp core.io wrote on a parquet stage file."""
    meta = pq.read_schema(io.stage_path(name)).metadata or {}
    return json.loads(meta[b"narco"])["provenance"]
