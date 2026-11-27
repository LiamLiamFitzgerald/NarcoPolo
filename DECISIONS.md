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
