# Decisions

Append only. Every decision that changes a default, a contract or a principle. Never rewrite earlier entries.

Format: `YYYY-MM-DD HH:MM · who · decision · why`

## Open decisions for Friday

- Region: West Cork (known cases) or south-east (validated inshore maps)?
- Fresh-code rule and judging details confirmed with the organisers?
- Does the CASSINI data cube cover the south coast?
- Does a cash prize count as commercial use of GFW data?

## Log
2026-11-27 17:25 · Liam (P1) · `raw/manifest.json` carries a top-level `latest` dict with ISO dates `radar`, `gfw_presence`, `gfw_sar`, `era5`; `core.config.snapshot_date` takes their minimum (A11) · the Data dictionary says what the manifest lists per file but not where the latest dates live; P2 writes them
2026-11-27 17:40 · P7 · The dashboard stays one plain-JS `dashboard/index.html`; a thin pywebview window (`dashboard/app.py`) hosts it and serves the snapshot through `js_api`, so it works offline and the spec's single-file rule holds · the user chose pywebview for the front end; pywebview must be added to pyproject.toml by P1
2026-11-27 18:30 · Liam (P1) · every pipeline module exposes a zero-argument `run() -> None` (reads its input stage files, writes its outputs through core.io); `make all` calls them in order reference, coverage, detect, match, aggregate, forecast, detectors, fuse, patrol, export (`scripts/run_all.py`). The named functions in the specs stay public and `run()` may just call them · the Make targets name functions with different argument lists (`build_exposure(passes, cells, era5)`, `write_events(...)`), so one uniform entry point is the simplest way to chain them
