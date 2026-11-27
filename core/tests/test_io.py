import shutil

import pandas as pd
import pytest

from core import io
from core.tests.test_schemas import frame


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    cfg = tmp_path / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    monkeypatch.setattr(io, "CONFIG_PATH", cfg)
    return cfg


def test_round_trip_every_parquet_stage():
    for name in io.SCHEMAS:
        if name in io._GPKG:
            continue
        io.write_stage(name, frame(name), "simulated")
        back = io.read_stage(name)
        assert (
            len(back) == 1
            and list(back.columns) == list(frame(name).columns)
            or set(back.columns) == set(frame(name).columns)
        )


def test_writing_count_with_zero_exposure_raises():
    bad = frame("aggregate/observed", count=1.0, exposure=0.0)
    with pytest.raises(Exception, match="exposure = 0"):
        io.write_stage("aggregate/observed", bad, "simulated")
    assert not io.stage_path("aggregate/observed").exists()


def test_stamp_has_seed_or_real(sandbox):
    io.write_stage("aggregate/observed", frame("aggregate/observed"), "real")
    import pyarrow.parquet as pq

    meta = pq.read_table(io.stage_path("aggregate/observed")).schema.metadata[b"narco"]
    assert b'"seed": "real"' in meta


def test_only_the_keys_a_stage_reads_make_it_stale(sandbox):
    io.write_stage("aggregate/observed", frame("aggregate/observed"), "simulated")
    io.write_stage("forecast/expected", frame("forecast/expected"), "simulated")
    sandbox.write_text(
        sandbox.read_text().replace("embargo_days: 7", "embargo_days: 14")
    )  # only `split` changes
    io.read_stage("aggregate/observed")  # does not read split: still fresh
    with pytest.raises(ValueError, match="stale"):
        io.read_stage("forecast/expected")


def test_sim_change_stales_simulated_files_only(sandbox):
    io.write_stage("aggregate/observed", frame("aggregate/observed"), "simulated")
    io.write_stage("fuse/cells", frame("fuse/cells"), "real")
    sandbox.write_text(sandbox.read_text().replace("beta0: -4", "beta0: -5"))
    with pytest.raises(ValueError, match="stale"):
        io.read_stage("aggregate/observed")
    io.read_stage("fuse/cells")


def test_unstamped_file_and_bad_names_and_gpkg():
    p = io.stage_path("aggregate/observed")
    p.parent.mkdir(parents=True)
    frame("aggregate/observed").to_parquet(p)
    with pytest.raises(ValueError, match="stamp"):
        io.read_stage("aggregate/observed")
    with pytest.raises(KeyError):
        io.stage_path("nope/nothing")
    with pytest.raises(NotImplementedError):
        io.read_stage("reference/cells")
    assert io.stage_path("aggregate/observed").name == "observed.parquet"
    assert isinstance(pd.read_parquet(p), pd.DataFrame)
