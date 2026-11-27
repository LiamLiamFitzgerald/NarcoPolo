import http.server
import json
import re
import sys
import threading
import urllib.request
from pathlib import Path

from dashboard import app
from dashboard.app import Api

HTML = (Path(__file__).parents[1] / "index.html").read_text()
SPEC_FUNCTIONS = [
    "loadSnapshot", "project", "drawBasemap", "drawHeatmap", "hatchUnobserved",
    "drawOverlays", "drawSiteList", "drawPlan", "drawValidation", "drawBanner", "onWeekChange",
]  # fmt: skip


def test_every_spec_function_is_defined():
    for name in SPEC_FUNCTIONS:
        assert re.search(rf"(async )?function {name}\(", HTML), name


def test_page_loads_nothing_from_the_internet():
    assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", HTML)


def test_page_computes_no_scores():
    # the browser may sort and format; it must not derive any statistic (docs/specs/P7.md)
    assert not re.search(r"Math\.(log|exp|sqrt|pow)\b|\.reduce\(", HTML)


def test_main_falls_back_to_the_browser_without_pywebview(monkeypatch):
    called = []
    monkeypatch.setitem(sys.modules, "webview", None)  # makes `import webview` raise ImportError
    monkeypatch.setattr(app, "_browser", lambda: called.append(1))
    app.main()
    assert called == [1]


def test_api_serves_the_snapshot_file(tmp_path):
    p = tmp_path / "snapshot.json"
    p.write_text(json.dumps({"meta": {"data_label": "simulated"}}))
    assert Api(p).get_snapshot()["meta"]["data_label"] == "simulated"


def test_snapshot_path_follows_the_data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("NARCO_DATA", str(tmp_path))
    assert app._snapshot_path() == tmp_path / "export" / "snapshot.json"


def test_fallback_server_serves_the_page_and_the_snapshot(tmp_path):
    snap = tmp_path / "snapshot.json"
    snap.write_text('{"meta": {"data_label": "real"}}')
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), app._handler(snap)) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_port}"
        assert (
            json.load(urllib.request.urlopen(f"{base}/snapshot.json"))["meta"]["data_label"]
            == "real"
        )
        assert b"drawBanner" in urllib.request.urlopen(f"{base}/index.html").read()
        srv.shutdown()
