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


def test_stub_shapes():
    from detectors import bh, cusum, fuse, tail_pmid

    assert tail_pmid([0.0, 1.0], [1.0, 1.0], [1.0, 1.0]).tolist() == [1.0, 1.0]
    assert not bh([0.5, 0.5]).any()
    assert cusum([1.0], [1.0], [1.0]).tolist() == [0.0]
    U, agreement = fuse(cusum([1.0, 2.0], [1.0, 1.0], [1.0, 1.0]).reshape(-1, 1))
    assert len(U) == len(agreement) == 2
