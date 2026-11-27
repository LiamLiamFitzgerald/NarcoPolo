import shutil

import pytest

from core import io
from core.config import load
from sim.simulate import simulate


@pytest.fixture(scope="module")
def sim_data(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p6")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    cfg = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    mp.setattr(io, "CONFIG_PATH", cfg)
    simulate(load(cfg)[0], 20261127)
    yield
    mp.undo()


def test_run_writes_schema_valid_cells_for_observed_rows_only(sim_data):
    import detectors

    detectors.run()
    cells = io.read_stage("fuse/cells")  # read_stage re-checks the schema
    obs = io.read_stage("aggregate/observed")
    keys = ["cell_id", "date", "event_type"]
    seen = obs[obs["exposure"] > 0][keys].astype(str)
    assert len(cells) > 0
    assert cells[keys].astype(str).merge(seen).shape[0] == len(cells)  # no unobserved row is scored


def test_stub_shapes():  # fuse stays a stub until issue 55
    import pandas as pd

    from detectors import fuse

    U, agreement = fuse(pd.DataFrame({"cusum_s": [0.0, 1.0]}))
    assert len(U) == len(agreement) == 2
