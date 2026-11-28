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
    io.write_stage(
        "reference/cells", frame("reference/cells"), "simulated"
    )  # every cell_id must exist here
    return cfg


def test_round_trip_every_parquet_stage():
    for name in io.SCHEMAS:
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
    assert io.stage_path("aggregate/observed").name == "observed.parquet"
    assert isinstance(pd.read_parquet(p), pd.DataFrame)


def test_date_reads_back_as_timestamps():
    io.write_stage("aggregate/observed", frame("aggregate/observed"), "simulated")
    assert pd.api.types.is_datetime64_dtype(io.read_stage("aggregate/observed")["date"])


def test_raster_paths_sit_under_the_data_root():
    assert (
        io.raster_path("reference/sea_250m")
        == io.stage_path("reference/cells").parent / "sea_250m.tif"
    )
    with pytest.raises(KeyError):
        io.raster_path("reference/nope")


@pytest.mark.parametrize("provenance", ["simulated", "real"])
@pytest.mark.parametrize("name", ["aggregate/observed", "reference/cells"])
def test_read_provenance_round_trips(name, provenance):
    io.write_stage(name, frame(name), provenance)
    assert io.read_provenance(name) == provenance


def test_read_provenance_without_stamp_raises():
    io._sidecar("reference/cells").unlink()
    with pytest.raises(ValueError, match="no config stamp"):
        io.read_provenance("reference/cells")


def test_read_cells_drops_geometry():
    cells = io.read_cells()
    assert "geometry" not in cells.columns and "cell_id" in cells.columns


# #171: stricter types, so format drift fails at write time


def test_dates_must_be_naive_midnight():
    ok = frame("aggregate/observed")
    io.write_stage("aggregate/observed", ok, "simulated")
    for bad in (pd.Timestamp("2026-08-01 12:00"), pd.Timestamp("2026-08-01", tz="UTC")):
        with pytest.raises(Exception, match="calendar dates"):
            io.write_stage("aggregate/observed", ok.assign(date=[bad]), "simulated")


def test_dates_are_stored_as_one_type_whatever_the_writer_passed():
    from datetime import date

    import pyarrow.parquet as pq

    for d in (date(2026, 8, 1), pd.Timestamp("2026-08-01")):
        io.write_stage(
            "aggregate/observed", frame("aggregate/observed").assign(date=[d]), "simulated"
        )
        t = pq.read_schema(io.stage_path("aggregate/observed")).field("date").type
        assert str(t) == "timestamp[ns]"


def test_numeric_ids_are_rejected():
    from pandera.errors import SchemaErrors

    with pytest.raises(SchemaErrors):
        io.write_stage(
            "detect/detections", frame("detect/detections").assign(pass_id=[7]), "simulated"
        )


def test_an_empty_string_dtype_id_column_is_valid():
    """0 rows with pandas' string dtype (what match writes when there are no events) pass the id check."""
    empty = frame("detect/detections").iloc[0:0].astype({"pass_id": "string"})
    io.write_stage("detect/detections", empty, "simulated")
    assert io.read_stage("detect/detections").empty


def test_an_empty_sites_file_keeps_its_list_types():
    """A 0-row fuse/sites gets the same Arrow types as a non-empty one, not `null`."""
    import pyarrow.parquet as pq

    full = frame("fuse/sites")
    io.write_stage("fuse/sites", full, "simulated")
    want = pq.read_schema(io.stage_path("fuse/sites"))
    io.write_stage("fuse/sites", full.iloc[0:0], "simulated")
    got = pq.read_schema(io.stage_path("fuse/sites"))
    for col in ("reasons", "top_piers", "site_id"):
        assert got.field(col).type == want.field(col).type
    assert io.read_stage("fuse/sites").empty
