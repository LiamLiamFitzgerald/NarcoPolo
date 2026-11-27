# Status

One line per module, updated at every merge. Format: what works on the simulator · what works on real data · what's blocked.

| Module | Simulator | Real data | Blocked |
| --- | --- | --- | --- |
| P1 core, sim, validate, CI | core, schemas, io, sim tables, make targets, validate (7 of 10 checks) merged | n/a until P2 data | sim scene chips and raw files (#92-94); validate injection, null, backtest wait for P4, P6, P5 |
| P2 ingest | — | — | — |
| P3 reference, coverage | stubs for every public function; run() checks the simulated reference and coverage files (#22) | — | real layers need P3 config keys, post_storm column, raster paths (#85); module tests not collected by CI (#96) |
| P4 detect, match | — | — | — |
| P5 aggregate, forecast | — | — | — |
| P6 detectors, fuse | — | — | — |
| P7 patrol, export, dashboard | — | — | — |

## Checkpoints

- [ ] Fri 22:00 contracts frozen
- [ ] Sat 02:00 stubs run end to end on the simulator
- [ ] Sat 12:00 real data cached; dashboard on the simulator
- [ ] Sat 18:00 human map checks (exclusion zones)
- [ ] Sat 22:00 real snapshot
- [ ] Sun 10:00 demo video
- [ ] Sun 13:00 code freeze
- [ ] Sun 15:00 submit
