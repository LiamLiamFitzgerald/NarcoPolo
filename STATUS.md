# Status

One line per module, updated at every merge. Format: what works on the simulator · what works on real data · what's blocked.

| Module | Simulator | Real data | Blocked |
| --- | --- | --- | --- |
| P1 core, sim, validate, CI | all core, sim (stage + raw files), make targets; validate: all 10 checks incl. injection, null, backtest; contracts #85 #87 #88 #98 in; rasterio + netCDF4 added; L1 (#150): drop regimes fixed, two_sites, pass_aware, displacing, null and `sim.patrol_outcome`; config `p4:` block (P4 spec Parameters, #183) | n/a until P2 data | null test and planted-site rank wait for P6's real fuse; #117 (CI over every module) waits for other modules' type errors |
| P2 ingest | `ingest/cache` (PR #53); offline stubs for probe, s1, gfw, era5, osm, static, run write sim-shaped raw/ files recorded with a licence, `fetch_all` exported (#21) | — | real fetchers not started; P2 tests not in pytest testpaths (P1, see #117) |
| P3 reference, coverage | stubs (#22); reference/cells real layers on the simulator: cells, inshore_frac (NaN outside survey), regrid_presence, lanes, anchorages, exclusion, to_coarse; thresholds from config `reference:` (#34) | — | masks #35, piers #36, coverage #37 in review |
| P4 detect, match | detector (CFAR, ghosts, p_boat) and matching on core (config, grid ids, Split, schemas, io); stand-ins gone; on the simulator detect.run and match.run keep the simulator's files (its chips only draw detected boats); validate.injection_test runs the real detector | — | real detect: where the p_boat model is fitted and stored (TODO(P1), #183); real match: GFW presence on the 2 km grid has no stage file (P3/P1 contract) |
| P5 aggregate, forecast | aggregate.run() and forecast.run() run end to end on P1's simulator; EWMA with zero-rate shrinkage, GLM on 2 km + EB per 10 km, NB intervals, fold 0 + backtest rows; skill finite; forecast 160 s at 730 days, 3.7 GB peak; D7/D8 (#175): PIT interval coverage in the report (0.900 slowdown EWMA, 0.906 dark_small GLM), slowdowns EWMA, dark_small GLM, slowdown skill < 0 on the sim | waits for P3 cells/coverage and P4 events | #74 item 5 (P6) |
| P6 detectors, fuse | detectors (mid-p + BH, Gi* checked against the textbook formula, CUSUM h calibrated on null runs, context incl. post_storm, U, agreement, y, y_week); fuse end to end on the simulator: lag link, sites, permutation over the top-15 (#177 options 1+3), recurrence, suppression, piers, reasons, L3/L4 columns; writes fuse/cells, fuse/sites, fuse/piers, fuse/links (157 sites on seed 20261127) | — | planted site needs detected pick-ups (0 of 11 on seed 20261127: P4 detect is a pass-through of the simulator's detections); null test with real cells waits for P1 #189; D1 ranking by p_site not yet done |
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
