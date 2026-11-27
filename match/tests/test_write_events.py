import pandas as pd
import pytest

from match import _standin, dark_small_events, ship_key, slowdowns_from_tracks, write_events
from match.tests.test_slowdowns import CELLS, _era5, _track

RAW_ID = "250123456"  # a made-up 9-digit MMSI-like id


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setitem(_standin.CFG, "x0", 0.0)
    monkeypatch.setitem(_standin.CFG, "y0", 0.0)
    monkeypatch.setenv(_standin.CFG["ship_key_salt_env"], "test-salt")


def test_ship_key_is_salted_and_stable(monkeypatch):
    k = ship_key(RAW_ID)
    assert k == ship_key(RAW_ID) and len(k) == 64 and RAW_ID not in k
    monkeypatch.setenv(_standin.CFG["ship_key_salt_env"], "other-salt")
    assert ship_key(RAW_ID) != k
    monkeypatch.delenv(_standin.CFG["ship_key_salt_env"])
    with pytest.raises(RuntimeError):
        ship_key(RAW_ID)


def test_events_file_is_schema_valid_and_never_holds_the_raw_id(tmp_path):
    slow = slowdowns_from_tracks(_track(ship_id=RAW_ID), cells=CELLS, era5=_era5({"0_0": [1.0]}))
    dets = pd.DataFrame({"det_id": ["p-0"], "pass_id": "p", "time_utc": pd.Timestamp("2026-11-03T06:30Z"),
                         "x_m": 1500.0, "y_m": 1500.0, "cell_id": "0_0", "size_class": "small", "p_boat": 0.4,
                         "matched": False})  # fmt: skip
    out = write_events(dark_small_events(dets), slow, out=tmp_path / "events.parquet")
    ev = pd.read_parquet(out)
    assert list(ev.columns) == _standin.EVENTS_COLUMNS and len(ev) == 2
    assert set(ev["event_type"]) == {"dark_small", "slowdown"} and str(ev["time_utc"].dt.tz) == "UTC"
    assert ev.loc[ev["event_type"] == "slowdown", "ship_key"].str.len().eq(64).all()
    assert RAW_ID.encode() not in out.read_bytes()


def test_write_events_refuses_raw_id_columns(tmp_path):
    bad = pd.DataFrame({"event_id": ["x"], "MMSI": [RAW_ID]})
    with pytest.raises(ValueError, match="raw ship identifiers"):
        write_events(bad, out=tmp_path / "e.parquet")


def test_empty_inputs_write_an_empty_valid_file(tmp_path):
    assert pd.read_parquet(write_events(out=tmp_path / "e.parquet")).empty
