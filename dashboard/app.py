"""Desktop window for the dashboard. Run: uv run python -m dashboard.app

Shows data/export/snapshot.json (or $NARCO_DATA/export/snapshot.json), written by `make all`."""

import functools
import http.server
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent


def _data_root() -> Path:
    return Path(os.environ.get("NARCO_DATA", HERE.parent / "data"))


def _snapshot_path() -> Path:
    return _data_root() / "export" / "snapshot.json"


# "We checked" patrol outcomes (#317). Places only: a site id, a week and one of three fixed answers; no free
# text, no vessel, no person. Once core.schemas declares patrol/outcomes (contract #329) they live in that stage
# file, which patrol learns from; until then they go to a plain draft file under the data root (#339).
OUTCOMES = ("found_something", "found_nothing", "not_visited")
_STAGE = "patrol/outcomes"
_COLS = ["site_id", "iso_week", "outcome", "entered_at"]


def _outcomes_path() -> Path:
    return _data_root() / "dashboard" / "outcomes_draft.json"


def _stage_ready() -> bool:
    from core.schemas import SCHEMAS

    return _STAGE in SCHEMAS


def _read_draft(path: Path) -> list[dict]:
    return json.loads(path.read_text()) if path.exists() else []


def _latest(rows: list[dict]) -> list[dict]:
    """One row per (site_id, iso_week): the latest entered_at wins (ISO strings sort in time order)."""
    by_key = {(r["site_id"], r["iso_week"]): r for r in sorted(rows, key=lambda r: r["entered_at"])}
    return list(by_key.values())


def _write_stage(rows: list[dict]) -> None:
    import pandas as pd

    from core import io

    frame = pd.DataFrame(rows, columns=_COLS)
    frame["entered_at"] = pd.to_datetime(frame["entered_at"], utc=True)
    io.write_stage(_STAGE, frame, "real")  # crews' answers are always real, whatever the snapshot


def _read_stage(draft: Path) -> list[dict]:
    """The stage file's rows. Draft rows are merged in once (the latest answer per site and week wins),
    then the draft is removed, so it can never be counted twice."""
    from core import io

    rows = []
    if io.stage_path(_STAGE).exists():
        f = io.read_stage(_STAGE)
        rows = [
            {
                **r,
                "outcome": str(r["outcome"]),
                "entered_at": r["entered_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            for r in f[_COLS].to_dict("records")
        ]
    if draft.exists():
        rows = _latest(rows + _read_draft(draft))
        _write_stage(rows)
        draft.unlink()
    return rows


def _read_outcomes(path: Path) -> list[dict]:
    return _read_stage(path) if _stage_ready() else _read_draft(path)


def _record_outcome(path: Path, site_id: str, iso_week: str, outcome: str) -> list[dict]:
    """Keep one answer per site and week (the latest); returns every row."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}")
    if not re.fullmatch(r"[\w-]{1,64}", site_id) or not re.fullmatch(r"\d{4}-W\d{2}", iso_week):
        raise ValueError("site_id or iso_week is malformed")
    rows = [r for r in _read_outcomes(path) if (r["site_id"], r["iso_week"]) != (site_id, iso_week)]
    rows.append(
        {
            "site_id": site_id,
            "iso_week": iso_week,
            "outcome": outcome,
            "entered_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    if _stage_ready():
        _write_stage(rows)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=1))
    return rows


class Api:
    """Exposed to index.html as window.pywebview.api: serves the frozen snapshot and keeps the crews'
    "we checked" answers (#317): in patrol/outcomes once the contract exists, else in the draft file."""

    def __init__(self, snapshot: Path | None = None, outcomes: Path | None = None):
        self._snapshot = snapshot or _snapshot_path()
        self._outcomes = outcomes or _outcomes_path()

    def get_snapshot(self) -> dict:
        return json.loads(self._snapshot.read_text())

    def get_outcomes(self) -> list[dict]:
        return _read_outcomes(self._outcomes)

    def record_outcome(self, site_id: str, iso_week: str, outcome: str) -> dict:
        """{"rows": every answer, "stored": "stage" (patrol learns from it) or "draft"}."""
        rows = _record_outcome(self._outcomes, site_id, iso_week, outcome)
        return {"rows": rows, "stored": "stage" if _stage_ready() else "draft"}


def _handler(snapshot: Path, outcomes: Path | None = None):
    """Serves the dashboard folder, the snapshot at /snapshot.json (it lives under the data root,
    which is not inside the dashboard folder) and the outcomes at /outcomes.json (POST adds one)."""
    api = Api(snapshot, outcomes)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def _json(self, code: int, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/snapshot.json":
                return self._json(200, snapshot.read_bytes())
            if path == "/outcomes.json":
                return self._json(200, json.dumps(api.get_outcomes()).encode())
            return super().do_GET()

        def do_POST(self):
            if self.path.split("?")[0] != "/outcomes.json":
                return self.send_error(404)
            try:
                n = min(int(self.headers.get("Content-Length", 0)), 4096)
                r = json.loads(self.rfile.read(n))
                res = api.record_outcome(str(r["site_id"]), str(r["iso_week"]), str(r["outcome"]))
            except (ValueError, KeyError, TypeError):
                return self.send_error(400)
            self._json(200, json.dumps(res).encode())

    return functools.partial(Handler, directory=str(HERE))


def _browser() -> None:
    """Fallback with no GUI backend: serve the page on 127.0.0.1 only (no internet) and open it in
    the default browser."""
    import webbrowser

    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler(_snapshot_path())) as srv:
        url = f"http://127.0.0.1:{srv.server_port}/index.html"
        print(f"No pywebview window available; serving {url} (Ctrl+C to stop)")
        webbrowser.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass


def main() -> None:
    try:
        import webview  # imported here so tests and the pipeline run without pywebview installed
        from webview.errors import WebViewException
    except ImportError:
        return _browser()
    webview.create_window(
        "NarcoPolo", str(HERE / "index.html"), js_api=Api(), width=1400, height=900
    )
    try:
        webview.start()
    except WebViewException:  # neither GTK nor Qt is usable
        _browser()


if __name__ == "__main__":
    main()
