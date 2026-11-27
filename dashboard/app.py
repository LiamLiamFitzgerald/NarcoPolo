"""Desktop window for the dashboard. Run: uv run python -m dashboard.app

Shows data/export/snapshot.json (or $NARCO_DATA/export/snapshot.json), written by `make all`."""

import functools
import http.server
import json
import os
from pathlib import Path

HERE = Path(__file__).parent


def _snapshot_path() -> Path:
    return Path(os.environ.get("NARCO_DATA", HERE.parent / "data")) / "export" / "snapshot.json"


class Api:
    """Exposed to index.html as window.pywebview.api; serves the frozen snapshot, nothing else."""

    def __init__(self, snapshot: Path | None = None):
        self._snapshot = snapshot or _snapshot_path()

    def get_snapshot(self) -> dict:
        return json.loads(self._snapshot.read_text())


def _handler(snapshot: Path):
    """Serves the dashboard folder, and the snapshot at /snapshot.json (it lives under the data
    root, which is not inside the dashboard folder)."""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] != "/snapshot.json":
                return super().do_GET()
            body = snapshot.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
    except ImportError:
        return _browser()
    webview.create_window(
        "NarcoPolo", str(HERE / "index.html"), js_api=Api(), width=1400, height=900
    )
    try:
        webview.start()
    except webview.errors.WebViewException:  # neither GTK nor Qt is usable
        _browser()


if __name__ == "__main__":
    main()
