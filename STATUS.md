# Status

One line per module, updated at every merge. Format: what works on the simulator · what works on real data · what's blocked.

| Module | Simulator | Real data | Blocked |
| --- | --- | --- | --- |
| P1 core, sim, validate, CI | core, sim (all raw files), make targets, validate: 8 of 10 checks incl. backtest; #58, #74, #90 settled | n/a until P2 data | validate injection and null tests (prompts A, B) wait for P4 detect and P6 fuse; #117 (CI on every module) waits for other modules' type errors |
| P2 ingest | `ingest/cache` (request_key, cached, record) tested, manifest matches sim/raw.py, PR #53 | — | #21 stubs still open |
| P3 reference, coverage | — | — | — |
| P4 detect, match | — | — | — |
| P5 aggregate, forecast | aggregate.run() and forecast.run() run end to end on P1's simulator; EWMA with zero-rate shrinkage, GLM on 2 km + EB per 10 km (#58), NB intervals, fold 0 + backtest rows; skill finite | waits for P3 cells/coverage and P4 events | #74 item 5 (P6); forecast takes ~4 min at 730 days |
| P6 detectors, fuse | stubs: `detectors.run()` and `fuse.run()` write schema-valid placeholder fuse/cells and fuse/sites (#24) | — | P6 tests not in pytest testpaths (P1) |
| P7 patrol, export, dashboard | placeholder stubs run end to end; dashboard renders them in pywebview (issue 25) | — | real logic waits on issues 49, 50, 51 |

## Checkpoints

- [ ] Fri 22:00 contracts frozen
- [ ] Sat 02:00 stubs run end to end on the simulator
- [ ] Sat 12:00 real data cached; dashboard on the simulator
- [ ] Sat 18:00 human map checks (exclusion zones)
- [ ] Sat 22:00 real snapshot
- [ ] Sun 10:00 demo video
- [ ] Sun 13:00 code freeze
- [ ] Sun 15:00 submit
