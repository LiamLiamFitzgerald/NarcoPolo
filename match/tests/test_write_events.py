import pandas as pd
import pytest

from core import io
from match import dark_small_events, ship_key, slowdowns_from_tracks, write_events
from match._common import CFG
from match.events import EVENTS_COLUMNS
from match.tests.test_slowdowns import CELLS, _era5, _track

RAW_ID = "250123456"  # a made-up 9-digit MMSI-like id


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(
        "core.grid._origin", lambda: (0.0, 0.0)
    )  # cells 2000_0_0, 2000_1_0, ... at the origin
    monkeypatch.setenv(CFG["ship_key_salt_env"], "test-salt")


def test_ship_key_is_salted_and_stable(monkeypatch):
    k = ship_key(RAW_ID)
    assert k == ship_key(RAW_ID) and len(k) == 64 and RAW_ID not in k
    monkeypatch.setenv(CFG["ship_key_salt_env"], "other-salt")
    assert ship_key(RAW_ID) != k
    monkeypatch.delenv(CFG["ship_key_salt_env"])
    with pytest.raises(RuntimeError):
        ship_key(RAW_ID)


@pytest.fixture(scope="module")
def sim_cell(tmp_path_factory):
    """A simulated data dir (core.io only writes cell_ids that exist in reference/cells); one of its cells."""
    import shutil

    from core.config import load
    from sim.simulate import simulate

    tmp = tmp_path_factory.mktemp("p4w")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    cfg = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    mp.setattr(io, "CONFIG_PATH", cfg)
    simulate(load(cfg)[0], 20261127)
    yield str(io.read_stage("reference/cells")["cell_id"].iloc[0])
    mp.undo()


@pytest.fixture
def data(sim_cell):
    return sim_cell


def test_events_file_is_schema_valid_and_never_holds_the_raw_id(data):
    slow = slowdowns_from_tracks(
        _track(ship_id=RAW_ID), cells=CELLS, era5=_era5({"2000_0_0": [1.0]})
    )
    dets = pd.DataFrame({"det_id": ["p-0"], "pass_id": "p", "time_utc": pd.Timestamp("2026-11-03T06:30Z"),
                         "x_m": 1500.0, "y_m": 1500.0, "cell_id": "2000_0_0", "size_class": "small", "p_boat": 0.4,
                         "matched": False})  # fmt: skip
    frames = [
        f.assign(cell_id=data) for f in (dark_small_events(dets), slow)
    ]  # a cell reference/cells has
    write_events(*frames, provenance="simulated")
    out = io.stage_path("match/events")
    ev = pd.read_parquet(out)
    assert list(ev.columns) == EVENTS_COLUMNS and len(ev) == 2
    assert (
        set(ev["event_type"]) == {"dark_small", "slowdown"} and str(ev["time_utc"].dt.tz) == "UTC"
    )
    assert ev.loc[ev["event_type"] == "slowdown", "ship_key"].str.len().eq(64).all()
    assert RAW_ID.encode() not in out.read_bytes()


def test_write_events_refuses_raw_id_columns(data):
    bad = pd.DataFrame({"event_id": ["x"], "MMSI": [RAW_ID]})
    with pytest.raises(ValueError, match="raw ship identifiers"):
        write_events(bad)


def test_empty_inputs_write_an_empty_valid_file(data):
    assert write_events(provenance="simulated").empty
