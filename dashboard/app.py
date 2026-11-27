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


def main() -> None:
    import webview  # imported here so tests and the pipeline run without pywebview installed

    webview.create_window(
        "NarcoPolo", str(HERE / "index.html"), js_api=Api(), width=1400, height=900
    )
    webview.start()


if __name__ == "__main__":
    main()
