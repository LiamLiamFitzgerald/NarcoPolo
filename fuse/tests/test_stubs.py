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


def test_zero_arg_run_writes_schema_valid_sites(sim_data):
    import fuse

    assert fuse.run() is None
    sites = io.read_stage("fuse/sites")  # read_stage re-checks the schema
    assert list(sites.columns) >= ["site_id", "S", "followup_unobserved"]


def test_pure_run_returns_cells_and_sites(sim_data):
    import fuse

    names = [
        "aggregate/observed",
        "forecast/expected",
        "reference/cells",
        "reference/travel_hours",
        "match/events",
    ]
    out = fuse.run(*(io.read_stage(n) for n in names))
    assert out is not None
    cells, sites = out
    io.write_stage("fuse/cells", cells, "simulated")  # schema-valid, even when empty
    io.write_stage("fuse/sites", sites, "simulated")


def test_unobserved_followup_is_none_not_zero():
    from fuse import followup_exposure, link_score

    assert followup_exposure(None, None, None) == 0.0
    assert link_score(None, None, None) is None
