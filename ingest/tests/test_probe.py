"""ingest/probe: one GFW presence query plus a Sentinel-1 pass listing, offline."""

import socket

import pandas as pd
import pytest

from ingest import probe, s1


@pytest.fixture(autouse=True)
def raw(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setenv("NARCO_RAW", str(tmp_path))
    return tmp_path


def test_go_when_both_answer(raw, fake_gfw, monkeypatch):
    monkeypatch.setattr(s1, "list_passes", lambda bbox, a, b: pd.DataFrame({"pass_id": ["p"]}))
    s1_ok, gfw_ok, notes = probe.probe()
    assert (s1_ok, gfw_ok) == (True, True) and "1 passes" in notes and "1 presence cells" in notes
    ((kind, kw),) = fake_gfw
    assert kind == "presence" and kw["start_date"] == kw["end_date"] and kw["filters"] is None
    assert list(raw.glob("gfw/*.parquet"))  # the query is on disk, through the cache


def test_no_go_when_s1_lists_nothing(fake_gfw):
    s1_ok, gfw_ok, _ = probe.probe()  # the current s1 stub lists no passes
    assert (s1_ok, gfw_ok) == (False, True)


def test_failure_is_reported_without_the_token(fake_gfw, monkeypatch):
    monkeypatch.setenv("GFW_TOKEN", "secret-token-value")

    def boom(req):
        raise RuntimeError("401 for token secret-token-value")

    monkeypatch.setattr(probe.gfw, "_query", boom)
    monkeypatch.setattr(s1, "list_passes", lambda *a: (_ for _ in ()).throw(OSError("no route")))
    s1_ok, gfw_ok, notes = probe.probe()
    assert (s1_ok, gfw_ok) == (False, False)
    assert "RuntimeError" in notes and "OSError" in notes and "secret-token-value" not in notes
