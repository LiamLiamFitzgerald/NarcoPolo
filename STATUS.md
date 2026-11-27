# Status

One line per module, updated at every merge. Format: what works on the simulator · what works on real data · what's blocked.

| Module | Simulator | Real data | Blocked |
| --- | --- | --- | --- |
| P1 core, sim, validate, CI | core, sim (all raw files), make targets, validate: 8 of 10 checks incl. backtest; #58, #74, #90 settled | n/a until P2 data | validate injection and null tests (prompts A, B) wait for P4 detect and P6 fuse; #117 (CI on every module) waits for other modules' type errors |
| P2 ingest | `ingest/cache` (request_key, cached, record) tested, manifest matches sim/raw.py, PR #53 | — | #21 stubs still open |
| P3 reference, coverage | — | — | — |
| P4 detect, match | — | — | — |
| P5 aggregate, forecast | aggregate.run() and forecast.run() on core.io and snapshot.json; observed, EWMA, GLM + EB, NB intervals, fold 0 + backtest rows (PR #66) | waits for P3 cells/coverage and P4 events | #90 (sim small-boat events on rough passes); #58 (lane bias, zero rates); #69 (P5 config keys, testpaths); #74 |
| P6 detectors, fuse | stubs: `detectors.run()` and `fuse.run()` write schema-valid placeholder fuse/cells and fuse/sites (#24) | — | P6 tests not in pytest testpaths (P1) |
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
