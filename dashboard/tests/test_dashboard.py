import http.server
import json
import re
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

from core import io
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


def test_site_list_ranks_by_p_site_then_s():
    # D1 (#176): p_site ranks sites, S breaks ties; sites without p_site follow, by S
    src = re.search(r"function siteOrder\(.*?\n\}\n", HTML, re.DOTALL)
    assert src, "siteOrder not found"
    sites = [
        {"id": "a", "p_site": 0.2, "S": 9.0},
        {"id": "b", "p_site": 0.8, "S": 1.0},
        {"id": "c", "p_site": 0.8, "S": 5.0},
        {"id": "d", "S": 7.0},
        {"id": "e", "p_site": None, "S": 8.0},
    ]
    js = (
        src.group(0)
        + f"console.log(JSON.stringify({json.dumps(sites)}.sort(siteOrder).map(s => s.id)))"
    )
    # the node binary that ships with basedpyright (dev dependency), so no new tool
    out = subprocess.run(
        [sys.executable, "-m", "nodejs_wheel", "-e", js], capture_output=True, text=True, check=True
    ).stdout
    assert json.loads(out) == ["c", "b", "a", "e", "d"]


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


# The Material Design theme (#249) must not break the demo rules: one offline file, colours only in
# the token block, every theme defines every token, and the data label always has its own style.
SIZE_BUDGET = 150_000  # bytes, no data; raised from 100 KB for the five briefing screens and seven charts (#318, #276): about 103 KB
# 3-character hex needs a letter, so issue references such as #176 are not colours
HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#(?=[0-9]*[a-fA-F])[0-9a-fA-F]{3}\b")


def _token_block() -> tuple[str, str]:
    start, end = HTML.index("/* tokens:start"), HTML.index("/* tokens:end */")
    return HTML[start:end], HTML[:start] + HTML[end:]


def test_page_stays_small_and_loads_nothing_external():
    assert len(HTML.encode()) < SIZE_BUDGET
    assert not re.search(r"<link\b|@import|url\(\s*['\"]?https?:|<script[^>]+src=", HTML)


def test_every_colour_lives_in_the_token_block():
    tokens, rest = _token_block()
    assert HEX.search(tokens)
    assert not HEX.findall(rest), "use a token (var(--...)) instead of a colour literal"
    assert not re.search(r"\brgba?\(|\bhsla?\(", rest)


def test_light_and_dark_define_the_same_tokens():
    tokens, _ = _token_block()
    light, dark = tokens.split(':root[data-mode="dark"]')
    names = lambda block: set(re.findall(r"(--[\w-]+)\s*:", block))
    assert names(light) == names(dark) and len(names(light)) > 40


def test_each_data_label_has_its_own_fixed_style():
    for label in ("simulated", "real", "mixed"):
        assert f'#banner[data-label="{label}"]' in HTML
    tokens, _ = _token_block()
    light, dark = tokens.split(':root[data-mode="dark"]')
    for label in ("simulated", "real", "mixed"):  # the label colours are the same in both themes
        colour = [re.findall(rf"--label-{label}:\s*(#\w+)", block) for block in (light, dark)]
        assert colour[0] == colour[1] and len(colour[0]) == 1


def test_motion_and_hatching_rules_are_kept():
    assert "prefers-reduced-motion: reduce" in HTML
    assert (
        ".cell.hatched { fill: url(#hatch); }" in HTML
    )  # unobserved is a pattern, never a scale step


# Words before numbers (#315): no sentence on the page may claim more than the system knows.
BANNED = re.compile(r"\b(detected|suspect vessels?|confirmed|smuggling detected)\b", re.IGNORECASE)


def test_phrases_live_in_one_block_and_use_the_fixed_vocabulary():
    start, end = HTML.index("// phrases:start"), HTML.index("// phrases:end")
    block = HTML[start:end]
    assert "const PHRASES = {" in block and "worth checking" in block.lower()
    # every quoted string in the page's script and every visible text node, not only the phrase block
    script = HTML[HTML.index("<script>\n// Plain JavaScript") :]
    strings = re.findall(r"\"((?:[^\"\\\n]|\\.)*)\"|`((?:[^`\\]|\\.)*)`", script)
    text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", HTML, flags=re.DOTALL)
    words = [
        re.sub(r"\$\{[^}]*\}", "", x) for pair in strings for x in pair if x
    ]  # ${...} is code, not words
    hits = [x for x in words if BANNED.search(x)] + BANNED.findall(text)
    assert not hits, f"banned wording: {hits}"


def test_every_screen_has_a_nav_link_and_a_question():
    for name in ("this-week", "dropoff", "fisheries", "plan", "limits"):
        assert f'<a href="#{name}" data-screen="{name}">' in HTML
        assert re.search(
            rf'<section class="screen" data-screen="{name}"[^>]*>\s*<h2 class="screen-title"[^>]*>[^<]+\?</h2>',
            HTML,
        ), name


# "We checked" outcomes (#317), kept in the stage file patrol/outcomes (#329)
def test_outcomes_keep_one_answer_per_site_and_week_and_reject_anything_else(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    api = Api(tmp_path / "snapshot.json")
    assert api.get_outcomes() == []
    api.record_outcome("2000_1_2", "2026-W48", "found_nothing")
    rows = api.record_outcome("2000_1_2", "2026-W48", "found_something")  # a correction replaces
    assert [(r["site_id"], r["iso_week"], r["outcome"]) for r in rows] == [
        ("2000_1_2", "2026-W48", "found_something")
    ]
    assert set(rows[0]) == {"site_id", "iso_week", "outcome", "entered_at"}  # places only, no text
    for bad in (("2000_1_2", "2026-W48", "a boat called X"), ("a b", "2026-W48", "not_visited"),
                ("2000_1_2", "week 48", "not_visited")):  # fmt: skip
        try:
            api.record_outcome(*bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    assert len(api.get_outcomes()) == 1
    stored = io.read_stage("patrol/outcomes")  # the schema checks it on read
    assert (
        stored["outcome"].tolist() == ["found_something"]
        and io.read_provenance("patrol/outcomes") == "real"
    )


def test_draft_answers_move_into_the_stage_file_once(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    draft = app._draft_path()
    draft.parent.mkdir(parents=True)
    draft.write_text(json.dumps([{"site_id": "s1", "iso_week": "2026-W47", "outcome": "found_nothing",
                                  "entered_at": "2026-11-20T10:00:00Z"}]))  # fmt: skip
    rows = Api(tmp_path / "snapshot.json").record_outcome("s2", "2026-W48", "not_visited")
    assert sorted((r["site_id"], r["outcome"]) for r in rows) == [
        ("s1", "found_nothing"),
        ("s2", "not_visited"),
    ]
    assert not draft.exists()


def test_fallback_server_records_an_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    snap = tmp_path / "snapshot.json"
    snap.write_text("{}")
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), app._handler(snap)) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_port}/outcomes.json"
        body = json.dumps({"site_id": "s1", "iso_week": "2026-W48", "outcome": "not_visited"})
        req = urllib.request.Request(url, body.encode(), {"Content-Type": "application/json"})
        assert json.load(urllib.request.urlopen(req))[0]["outcome"] == "not_visited"
        assert json.load(urllib.request.urlopen(url))[0]["site_id"] == "s1"
        srv.shutdown()
