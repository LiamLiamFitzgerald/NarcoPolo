"""An offline stand-in for the GFW client: records every 4Wings call and returns canned rows."""

import pandas as pd
import pytest

from ingest import gfw

# Placeholders, not real GFW filter syntax (that is open in #212): the tests only check pass-through.
SETTINGS = {
    "chunk_days": 2,
    "filter_join": " & ",
    "sar_matched": {"true": "m=1", "false": "m=0"},
    "vessel_types": {"cargo": "vt=cargo", "tanker": "vt=tanker"},
    "speed_bins": {"0-2": "s<2", "2+": "s>=2"},
}
# identity fields the API can return; ingest must never keep them
IDENTITY = {"mmsi": "fake-id", "ship_name": "FAKE NAME", "imo": "fake-imo", "call_sign": "FAKE"}


class _Result:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def df(self, include=None):
        frame = pd.DataFrame(self.rows)
        return frame[[c for c in frame.columns if include is None or c in include]]


class FakeClient:
    def __init__(self, calls: list):
        self.calls = calls
        self.fourwings = self

    def create_sar_presence_report(self, **kw):
        self.calls.append(("sar", kw))
        if kw["filters"] == ["m=0"]:
            return _Result([])  # an empty answer is a valid answer
        return _Result(
            [{"date": "2026-11-01T05", "lat": 51.5, "lon": -9.0, "detections": 2, **IDENTITY}]
        )

    def create_ais_presence_report(self, **kw):
        self.calls.append(("presence", kw))
        return _Result([{"date": "2026-11-01", "lat": 51.6, "lon": -8.5, "hours": 1.5, **IDENTITY}])


@pytest.fixture
def fake_gfw(monkeypatch):
    """The list of (dataset, kwargs) calls the fake client received."""
    calls: list = []
    monkeypatch.setattr(gfw, "_client", lambda: FakeClient(calls))
    monkeypatch.setattr(gfw, "_settings", lambda: SETTINGS)
    monkeypatch.setattr(gfw, "_run", lambda result: result)  # fake calls are plain, not coroutines
    return calls
