"""The four detectors and their fusion. STUBS (issue 24): every function returns a neutral, schema-valid
placeholder; the real steps from docs/specs/P6.md come in later issues."""

import numpy as np
import pandas as pd

from core import io
from core.observed import Observed
from detectors._common import PARAMS, _provenance

_KEY = ["cell_id", "date", "event_type"]


def pearson_z(C, mu, phi) -> np.ndarray:  # stub, issue 24
    return np.zeros(len(C))


def tail_pmid(C, mu, phi) -> np.ndarray:  # stub, issue 24: 1 = "nothing surprising"
    return np.ones(len(C))


def bh(p, q=PARAMS["fdr_q"]) -> np.ndarray:  # stub, issue 24: must run once over the whole window
    return np.zeros(len(p), bool)


def gi_star(C_week, mu_week, cells, band_m=PARAMS["gi_band_m"], perm=PARAMS["gi_perm"], seed=None):
    return np.zeros(len(C_week))  # stub, issue 24


def cusum(C, mu, phi, rho=PARAMS["cusum_rho"], h=PARAMS["cusum_h"]) -> np.ndarray:  # stub, issue 24
    return np.zeros(len(C))


def context_small(layers, post_storm) -> np.ndarray:  # stub, issue 24
    return np.full(len(layers), 0.5)


def context_slowdown(layers, hours) -> np.ndarray:  # stub, issue 24
    return np.full(len(layers), 0.5)


def fuse(scores: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:  # stub, issue 24
    return np.full(len(scores), 0.5), np.zeros(len(scores), int)


def run_cells() -> None:
    """aggregate/observed + forecast/expected -> fuse/cells.parquet, observed rows (E > 0) only."""
    obs = Observed(io.read_stage("aggregate/observed")).observed_rows()
    m = obs.merge(io.read_stage("forecast/expected"), on=_KEY)
    C, mu, phi = m["count"].to_numpy(), m["mu"].to_numpy(), m["phi"].to_numpy()
    p_mid = tail_pmid(C, mu, phi)
    scores = m[_KEY].assign(
        p_mid=p_mid,
        bh_flag=bh(p_mid),
        gi_z=gi_star(
            C, mu, m["cell_id"]
        ),  # TODO(P6): weekly sums, then each day gets its week's gi_z
        cusum_s=cusum(C, mu, phi),
        context=context_small(m, None),  # TODO(P6): per event type, with layers and post_storm
    )
    scores["U"], scores["agreement"] = fuse(scores)
    io.write_stage("fuse/cells", scores, _provenance("aggregate/observed"))  # type: ignore[arg-type]
