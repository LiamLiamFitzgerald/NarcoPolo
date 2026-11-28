# Status

One line per module, updated at every merge. Format: what works on the simulator · what works on real data · what's blocked.

| Module | Simulator | Real data | Blocked |
| --- | --- | --- | --- |
| P1 core, sim, validate, CI | all core, sim (stage + raw files), make targets; validate: all 10 checks incl. injection, null, backtest; contracts #85 #87 #88 #98 in; rasterio + netCDF4 added; L1 (#150): drop regimes fixed, two_sites, pass_aware, displacing, null and `sim.patrol_outcome` | n/a until P2 data | null test and planted-site rank wait for P6's real fuse; #117 (CI over every module) waits for other modules' type errors |
| P2 ingest | `ingest/cache` (PR #53); offline stubs for probe, s1, gfw, osm, static, run (#21); real `ingest/era5` via cdsapi, tested on a fake CDS serving the simulator (#30); real `ingest/osm` via Overpass, road_access decided server-side (#31); #185 type error fixed | — | real fetch needs the CDS key (laptop) and `cdsapi` in pyproject (#215); dataset names/URLs in #216; P2 tests not in pytest testpaths (#215) |
| P3 reference, coverage | stubs (#22); reference/cells real layers on the simulator: cells, inshore_frac (NaN outside survey), regrid_presence, lanes, anchorages, exclusion, to_coarse; thresholds from config `reference:` (#34) | — | masks #35, piers #36, coverage #37 in review |
| P4 detect, match | — | — | — |
| P5 aggregate, forecast | aggregate.run() and forecast.run() run end to end on P1's simulator; EWMA with zero-rate shrinkage, GLM on 2 km + EB per 10 km, NB intervals, fold 0 + backtest rows; skill finite; forecast 160 s at 730 days, 3.7 GB peak | waits for P3 cells/coverage and P4 events | #156 (GLM separation from static_frac, P1's call); #74 item 5 (P6) |
| P6 detectors, fuse | cell detectors (mid-p + BH, weekly Gi*, Poisson CUSUM), context, rank fusion, U, agreement, y and y_week in fuse/cells; lag link table and link score (#54, #55, #56); L3 combined p (CCT, calibrate, BH comb_flag, agreement_merged) and L4 site_value with rung-0 fallback on fuse/sites (#152, PR open) | — | sites, pier scores, fuse/piers and fuse/links (#57, #59); post_storm now in coverage/exposure, not yet read |
| P7 patrol, export, dashboard | merged (PRs 81, 97, 99, 102): patrol, export and dashboard run on the simulator; plan and snapshot pass `core.schemas.check_json`; dashboard shows agreement dots on cells | — | `obs_vs_exp`, pier score, exploration bootstrap: contract issues 87, 88, 98; coastline: 105; base port and start time stay simulated stand-ins until config has them (103); sea raster, config keys: 89 |

## Checkpoints

- [ ] Fri 22:00 contracts frozen
- [ ] Sat 02:00 stubs run end to end on the simulator
- [ ] Sat 12:00 real data cached; dashboard on the simulator
- [ ] Sat 18:00 human map checks (exclusion zones)
- [ ] Sat 22:00 real snapshot
- [ ] Sun 10:00 demo video
- [ ] Sun 13:00 code freeze
- [ ] Sun 15:00 submit
