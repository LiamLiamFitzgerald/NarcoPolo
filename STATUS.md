# Status

One line per module, updated at every merge. Format: what works on the simulator · what works on real data · what's blocked.

| Module | Simulator | Real data | Blocked |
| --- | --- | --- | --- |
| P1 core, sim, validate, CI | core, schemas, io, sim tables, make targets, validate (7 of 10 checks) merged | n/a until P2 data | sim scene chips and raw files (#92-94); validate injection, null, backtest wait for P4, P6, P5 |
| P2 ingest | — | — | — |
| P3 reference, coverage | — | — | — |
| P4 detect, match | — | — | — |
| P5 aggregate, forecast | aggregate.run() and forecast.run() on core.io and snapshot.json; observed, EWMA, GLM + EB, NB intervals, fold 0 + backtest rows (PR #66) | waits for P3 cells/coverage and P4 events | #90 (sim small-boat events on rough passes); #58 (lane bias, zero rates); #69 (P5 config keys, testpaths); #74 |
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
