"""Desktop window for the dashboard. Run: uv run python -m dashboard.app

Shows data/export/snapshot.json (or $NARCO_DATA/export/snapshot.json), written by `make all`."""

import functools
import http.server
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from core import io

HERE = Path(__file__).parent


def _data_root() -> Path:
    return Path(os.environ.get("NARCO_DATA", HERE.parent / "data"))


def _snapshot_path() -> Path:
    return _data_root() / "export" / "snapshot.json"


# "We checked" patrol outcomes (#317): the stage file patrol/outcomes (contract #329), written through
# core.io, which patrol reads for next week's plan. Places only: a site id, a week and one of three fixed
# answers; no free text, no vessel, no person. One answer per site and week: a later one replaces it.
OUTCOMES = ("found_something", "found_nothing", "not_visited")


def _draft_path() -> Path:
    """Where answers went before #329 (a plain JSON list); moved into patrol/outcomes once, then removed."""
    return _data_root() / "dashboard" / "outcomes_draft.json"


def _frame(rows: list[dict]) -> pd.DataFrame:
    f = pd.DataFrame(rows, columns=["site_id", "iso_week", "outcome", "entered_at"])
    f["entered_at"] = pd.to_datetime(f["entered_at"], utc=True)
    return f.astype({"site_id": object, "iso_week": object, "outcome": object})


def _read_outcomes() -> list[dict]:
    draft = _draft_path()
    if draft.exists():  # once: carry draft answers over, keeping any already in the stage file
        old = json.loads(draft.read_text())
        _write(_latest(pd.concat([_frame(old), _stored()], ignore_index=True)))
        draft.unlink()
    f = _stored()
    return [
        {**r, "entered_at": r["entered_at"].strftime("%Y-%m-%dT%H:%M:%SZ")}
        for r in f.to_dict("records")
    ]


def _stored() -> pd.DataFrame:
    return (
        io.read_stage("patrol/outcomes")
        if io.stage_path("patrol/outcomes").exists()
        else _frame([])
    )


def _latest(f: pd.DataFrame) -> pd.DataFrame:
    return f.sort_values("entered_at").drop_duplicates(["site_id", "iso_week"], keep="last")


def _write(f: pd.DataFrame) -> None:
    io.write_stage(
        "patrol/outcomes", f.reset_index(drop=True), "real"
    )  # entered by crews, never simulated


def _record_outcome(site_id: str, iso_week: str, outcome: str) -> list[dict]:
    """Keep one answer per site and week (the latest); returns every row."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}")
    if not re.fullmatch(r"[\w-]{1,64}", site_id) or not re.fullmatch(r"\d{4}-W\d{2}", iso_week):
        raise ValueError("site_id or iso_week is malformed")
    _read_outcomes()  # moves a draft over first, if there is one
    new = _frame([{"site_id": site_id, "iso_week": iso_week, "outcome": outcome,
                   "entered_at": datetime.now(UTC)}])  # fmt: skip
    _write(_latest(pd.concat([_stored(), new], ignore_index=True)))
    return _read_outcomes()


class Api:
    """Exposed to index.html as window.pywebview.api: serves the frozen snapshot and keeps the crews'
    "we checked" answers in patrol/outcomes (#317, #329)."""

    def __init__(self, snapshot: Path | None = None):
        self._snapshot = snapshot or _snapshot_path()

    def get_snapshot(self) -> dict:
        return json.loads(self._snapshot.read_text())

    def get_outcomes(self) -> list[dict]:
        return _read_outcomes()

    def record_outcome(self, site_id: str, iso_week: str, outcome: str) -> list[dict]:
        return _record_outcome(site_id, iso_week, outcome)


def _handler(snapshot: Path):
    """Serves the dashboard folder, the snapshot at /snapshot.json (it lives under the data root,
    which is not inside the dashboard folder) and the outcomes at /outcomes.json (POST adds one)."""
    api = Api(snapshot)

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
                rows = api.record_outcome(str(r["site_id"]), str(r["iso_week"]), str(r["outcome"]))
            except (ValueError, KeyError, TypeError):
                return self.send_error(400)
            self._json(200, json.dumps(rows).encode())

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
