"""Desktop window for the dashboard. Run: uv run python -m dashboard.app

pywebview is not in pyproject.toml yet (P1 owns it): `uv add pywebview` once P1 approves."""

import json
from pathlib import Path

HERE = Path(__file__).parent


class Api:
    """Exposed to index.html as window.pywebview.api; serves the frozen snapshot, nothing else."""

    def __init__(self, snapshot: Path = HERE.parent / "export" / "snapshot.json"):
        self._snapshot = snapshot

    def get_snapshot(self) -> dict:
        return json.loads(self._snapshot.read_text())


def _browser() -> None:
    """Fallback with no GUI backend: serve the repo folder locally (127.0.0.1 only, no internet)
    and open the same page in the default browser, which fetches ../export/snapshot.json."""
    import functools
    import http.server
    import webbrowser

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(HERE.parent))
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as srv:
        url = f"http://127.0.0.1:{srv.server_port}/dashboard/index.html"
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
