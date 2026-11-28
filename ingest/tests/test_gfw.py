"""ingest/gfw against a mocked 4Wings client: the simulator's raw/ schema, the cache and the licence."""

import json
import socket
from datetime import date, timedelta
from itertools import pairwise

import pandas as pd
import pyarrow.parquet as pq
import pytest

import sim.simulate
from core import io
from core.config import load
from ingest import gfw
from ingest.tests.conftest import IDENTITY

CFG = load(io.CONFIG_PATH)[0]
BBOX = (-10.6, 51.1, -7.9, 51.95)
START, END = (
    date(2026, 11, 1),
    date(2026, 11, 3),
)  # 3 days, chunk_days 2 -> 2 calendar-aligned requests


@pytest.fixture(scope="module")
def simraw(tmp_path_factory):
    root = tmp_path_factory.mktemp("sim")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("NARCO_DATA", str(root / "data"))
        mp.setenv("NARCO_RAW", str(root / "raw"))
        sim.simulate.simulate(CFG, 20261127)
    return root / "raw"


@pytest.fixture(autouse=True)
def raw(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setenv("NARCO_RAW", str(tmp_path))
    return tmp_path


def _manifest(raw):
    return json.loads((raw / "manifest.json").read_text())["files"]


def _same_schema(path, simulated):
    assert (
        pq.read_schema(path).remove_metadata().equals(pq.read_schema(simulated).remove_metadata())
    )


def test_sar_one_row_per_detection(simraw, raw, fake_gfw):
    path = gfw.fetch_sar(BBOX, START, END)
    assert path == raw / "gfw_sar.parquet"
    _same_schema(path, simraw / "gfw_sar.parquet")
    df = pd.read_parquet(path)
    assert (
        len(df) == 2 * 2
    )  # 2 detections in the one cell-hour, per chunk; unmatched chunks are empty
    assert df["matched"].all() and df["scene_id"].isna().all() and df["length_m"].isna().all()
    assert (df["timestamp"] == pd.Timestamp("2026-11-01 05:00", tz="UTC")).all()
    assert (df["lon"] == -9.0).all() and (df["lat"] == 51.5).all()


def test_sar_requests(raw, fake_gfw):
    gfw.fetch_sar(BBOX, START, END)
    assert [kw["filters"] for _, kw in fake_gfw] == [["m=1"], ["m=1"], ["m=0"], ["m=0"]]
    first = fake_gfw[0][1]
    second = fake_gfw[1][1]
    assert (first["start_date"], first["end_date"]) == ("2026-11-01", "2026-11-01")
    assert (second["start_date"], second["end_date"]) == ("2026-11-02", "2026-11-03")
    assert first["spatial_resolution"] == "HIGH" and first["temporal_resolution"] == "HOURLY"
    ring = first["geojson"]["coordinates"][0]
    assert first["geojson"]["type"] == "Polygon" and ring[0] == ring[-1]
    assert {x for x, _ in ring} == {-10.6, -7.9} and {y for _, y in ring} == {51.1, 51.95}
    assert "group_by" not in first  # grouping by vessel would return identities


def test_presence_daily_with_type_and_speed_bin(simraw, raw, fake_gfw):
    path = gfw.fetch_presence(BBOX, START, END)
    assert path == raw / "gfw_presence.parquet"
    _same_schema(path, simraw / "gfw_presence.parquet")
    df = pd.read_parquet(path)
    assert len(df) == 2 * 2 * 2  # vessel types x speed bins x chunks, one cell each
    combos = set(zip(df["vessel_type"], df["speed_bin"], strict=True))
    assert combos == {(v, s) for v in ("cargo", "tanker") for s in ("0-2", "2+")}
    assert (df["hours"] == 1.5).all() and (df["date"] == date(2026, 11, 1)).all()
    filters = {kw["filters"][0] for _, kw in fake_gfw}
    assert "vt=cargo & s<2" in filters and len(filters) == 4
    assert {kw["temporal_resolution"] for _, kw in fake_gfw} == {"DAILY"}


@pytest.mark.parametrize("fetch", [gfw.fetch_sar, gfw.fetch_presence])
def test_no_identity_and_licence(raw, fake_gfw, fetch):
    path = fetch(BBOX, START, END)
    assert not set(IDENTITY) & set(pq.read_schema(path).names)
    for rel, entry in _manifest(raw).items():
        assert (raw / rel).is_file()
        assert "non-commercial" in entry["licence"] and "Global Fishing Watch" in entry["licence"]
    for p in raw.rglob("*.parquet"):  # chunk files too
        assert not set(IDENTITY) & set(pq.read_schema(p).names)


@pytest.mark.parametrize("fetch", [gfw.fetch_sar, gfw.fetch_presence])
def test_second_call_downloads_nothing(raw, fake_gfw, fetch):
    path = fetch(BBOX, START, END)
    n, files = len(fake_gfw), _manifest(raw)
    assert fetch(BBOX, START, END) == path
    assert len(fake_gfw) == n and _manifest(raw) == files
    path.unlink()  # the combined file is gone, the per-request files are not
    assert fetch(BBOX, START, END) == path and len(fake_gfw) == n


def test_chunks_follow_the_calendar():
    a = list(gfw._chunks(date(2026, 11, 1), date(2026, 11, 9), 4))
    b = list(gfw._chunks(date(2026, 11, 2), date(2026, 11, 10), 4))  # the window a day later
    assert a[0][0] == date(2026, 11, 1) and a[-1][1] == date(2026, 11, 9)
    assert all(x[1] + timedelta(days=1) == y[0] for x, y in pairwise(a))
    assert a[1] == (date(2026, 11, 4), date(2026, 11, 7)) and a[1] in b  # reused, not re-downloaded
    assert list(gfw._chunks(START, END, None)) == [(START, END)]


def test_missing_config_points_to_issue(monkeypatch):
    monkeypatch.setattr(gfw._stub, "config", dict)
    with pytest.raises(KeyError, match="#212"):
        gfw.fetch_presence(BBOX, START, END)


def test_token_only_from_env(monkeypatch):
    monkeypatch.delenv("GFW_TOKEN", raising=False)
    with pytest.raises(KeyError, match="GFW_TOKEN"):
        gfw._client()
