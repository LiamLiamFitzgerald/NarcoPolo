import json
import re
from pathlib import Path

from dashboard.app import Api

HTML = (Path(__file__).parents[1] / "index.html").read_text()
SPEC_FUNCTIONS = [
    "loadSnapshot", "project", "drawBasemap", "drawHeatmap", "hatchUnobserved",
    "drawOverlays", "drawSiteList", "drawPlan", "drawValidation", "drawBanner", "onWeekChange",
]  # fmt: skip


def test_every_spec_function_is_defined():
    for name in SPEC_FUNCTIONS:
        assert re.search(rf"function {name}\(", HTML), name


def test_page_loads_nothing_from_the_internet():
    assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", HTML)


def test_api_serves_the_snapshot_file(tmp_path):
    p = tmp_path / "snapshot.json"
    p.write_text(json.dumps({"meta": {"data_label": "simulated"}}))
    assert Api(p).get_snapshot()["meta"]["data_label"] == "simulated"
