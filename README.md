# NarcoPolo

**Find the drop, not the boat.**

Our entry to the 12th CASSINI Hackathon (*EU Space for Peace and Resilience*, 27–29 November 2026, Dublin site, run by NCI). We're working on Challenge 3: *Countering transnational crime and terrorism with space data*.

## The idea

Cocaine often reaches Ireland by sea. A cargo ship drops a load offshore, and small boats pick it up and land it at a quiet pier. Ireland has only a few patrol ships for a huge area of sea, so knowing **where to look** matters more than seeing every boat.

NarcoPolo looks for that pattern in open satellite data:

1. **Ship slowdowns.** AIS data shows cargo ships pausing where they normally wouldn't.
2. **Small-boat visits.** Copernicus Sentinel-1 radar shows small boats visiting the same spot 0–7 days later.
3. **What's normal.** Inshore fishing maps and each spot's own history give a forecast of normal activity, so ordinary fishing isn't flagged.
4. **Where it lands.** Sea-route travel times show which piers a drop site could reach.

The output is a weekly briefing: the **top 3 drop sites**, the **piers to watch**, a **ship patrol route** and an **aircraft sweep**, each with plain-language reasons.

## Principles

- **Places, not people.** No vessel or person identities leave the pipeline.
- **Unobserved is not zero.** Where the satellite didn't look, the map says "unobserved", never "empty".
- **No look-ahead.** Models are only ever fitted on data from before the period they score.
- **Honest limits.** Small boats in rough seas, and pick-ups between satellite passes, can be missed. We say so.

## Data

| Source | Use |
| --- | --- |
| Copernicus Sentinel-1 (via the Copernicus Data Space Ecosystem) | Radar images for small-boat detection |
| Copernicus ERA5 | Wind and waves, to know when small boats are visible |
| Global Fishing Watch | AIS presence (ship slowdowns) and radar detections matched to AIS |
| BIM / Marine Institute inshore maps, OpenStreetMap, INFOMAR | Normal fishing grounds, piers, coastline and bathymetry |

Each source keeps its own licence; see the data manifest once the pipeline runs. Global Fishing Watch data is used under its non-commercial terms. Powered by Global Fishing Watch.

## Running it

| make (Linux, macOS) | Windows (no make) | What it does |
| --- | --- | --- |
| `make sim` | `uv run python -m sim` | Synthetic region with known truth |
| `make all` | `uv run python -m scripts.run_all` | Every pipeline step, ending with export |
| `make validate` | `uv run python -m validate` | Full `reports/validation.json` (~35 min on the simulator), `"mode": "full"` |
| `make validate-quick` | `uv run python -m validate --quick` | Same report with the reduced counts in `config.yaml` `validate.quick`, `"mode": "quick"`: a demo check, not the full result |
| `make demo` | `uv run python -m scripts.demo` | `make all` on top of an existing validation report; never runs validate. Without a report the proof panel shows "validation not run" |

Before the pitch: `make sim` (or real data), `make validate` (or `make validate-quick`) once, then `make demo`.

## Status

🚧 Setting up. All code is written during the hackathon weekend.

## Team

Seven people, each owning one part of the pipeline: core and validation, ingest, reference layers, detection, forecasting, fusion, and patrol planning with the dashboard.
