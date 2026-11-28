# Status

One line per module, updated at every merge. Format: what works on the simulator · what works on real data · what's blocked.

| Module | Simulator | Real data | Blocked |
| --- | --- | --- | --- |
| P1 core, sim, validate, CI | all core, sim (stage + raw files), make targets; validate: all 10 checks incl. injection, null, backtest; contracts #85 #87 #88 #98 in; rasterio + netCDF4 added; L1 (#150): drop regimes fixed, two_sites, pass_aware, displacing, null and `sim.patrol_outcome` | n/a until P2 data | null test and planted-site rank wait for P6's real fuse; #117 (CI over every module) waits for other modules' type errors |
| P2 ingest | `ingest/cache` (PR #53); offline stubs for probe, s1, gfw, era5, osm, static, run write sim-shaped raw/ files recorded with a licence, `fetch_all` exported (#21) | — | real fetchers not started; P2 tests not in pytest testpaths (P1, see #117) |
| P3 reference, coverage | stubs for every public function; run() checks the simulated reference and coverage files; exposure writes post_storm (A9) (#22) | — | real layers (#34-#37) |
| P4 detect, match | — | — | — |
| P5 aggregate, forecast | aggregate.run() and forecast.run() on core.io and snapshot.json; observed, EWMA, GLM + EB, NB intervals, fold 0 + backtest rows (PR #66) | waits for P3 cells/coverage and P4 events | #90 (sim small-boat events on rough passes); #58 (lane bias, zero rates); #69 (P5 config keys, testpaths); #74 |
| P6 detectors, fuse | cell detectors (mid-p + BH, weekly Gi*, Poisson CUSUM), context, rank fusion, U, agreement, y and y_week in fuse/cells; lag link table and link score (#54, #55, #56) | — | sites, pier scores, fuse/piers and fuse/links (#57, #59); post_storm now in coverage/exposure, not yet read |
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
