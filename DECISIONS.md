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
2026-11-27 18:30 · Liam (P1) · every pipeline module exposes a zero-argument `run() -> None` (reads its input stage files, writes its outputs through core.io); `make all` calls them in order reference, coverage, detect, match, aggregate, forecast, detectors, fuse, patrol, export (`scripts/run_all.py`). The named functions in the specs stay public and `run()` may just call them · the Make targets name functions with different argument lists (`build_exposure(passes, cells, era5)`, `write_events(...)`), so one uniform entry point is the simplest way to chain them
2026-11-27 18:55 · P1 · `core.io.read_stage` returns every `date` column as pandas datetime64 (midnight), whatever type the writer stored · P5's forecast joined plain dates (from the simulator) to datetimes and failed; one read type for every module avoids that. Writers may still pass `datetime.date`.
2026-11-27 18:55 · P1 · added P5's `ewma_delta: 0.97`, `ewma_min_se: 3`, `interval: 0.9` to config.yaml (docs/specs/P5.md Parameters; issue #69) and to forecast/expected's `reads:` · forecast_all raises without them.
2026-11-27 19:08 · P5 · zero-rate rule (#58, delegated to P5 by P1 on PR #66): EWMA rates are shrunk towards the level above with `ewma_min_se` units of prior exposure, r_cell = (S_C + k·r_parent) ÷ (S_E + k) and r_parent = (S_C10 + k·r_region) ÷ (S_E10 + k), k = `ewma_min_se` = 3; the backtest's flat baseline is shrunk the same way towards the region rate. This replaces the hard "parent rate until S_E ≥ 3" switch · a cell with no events yet got μ = 0, so one later event made Poisson deviance infinite and backtest skill NaN or a fake 1.0; shrinkage keeps the spec's intent (thin cells sit near their parent), adds no new parameter, and treats model and flat baseline alike
