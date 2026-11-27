# Status

One line per module, updated at every merge. Format: what works on the simulator · what works on real data · what's blocked.

| Module | Simulator | Real data | Blocked |
| --- | --- | --- | --- |
| P1 core, sim, validate, CI | core, sim (all raw files), make targets, validate: 8 of 10 checks incl. backtest; #58, #74, #90 settled | n/a until P2 data | validate injection and null tests (prompts A, B) wait for P4 detect and P6 fuse; #117 (CI on every module) waits for other modules' type errors |
| P2 ingest | `ingest/cache` (request_key, cached, record) tested, manifest matches sim/raw.py, PR #53 | — | #21 stubs still open |
| P3 reference, coverage | — | — | — |
| P4 detect, match | — | — | — |
| P5 aggregate, forecast | aggregate.run() and forecast.run() on core.io and snapshot.json; observed, EWMA, GLM + EB, NB intervals, fold 0 + backtest rows (PR #66) | waits for P3 cells/coverage and P4 events | #90 (sim small-boat events on rough passes); #58 (lane bias, zero rates); #69 (P5 config keys, testpaths); #74 |
| P6 detectors, fuse | mid-p + BH, weekly Gi*, Poisson CUSUM (h = 0.5 from the simulator null) fill fuse/cells for the evaluation window (#54); context rules + rank fusion give U and agreement, planted drop cell-days rank top decile with agreement ≥ 2 (#55); lag link: follow-up exposure X, link score L (None when X = 0, U_small = 0 on C = 0), link table lookup = direct L for every simulator slowdown, 0.5 s on the simulator (#56); fuse/ sites still stubs (#24) | — | link needs dark_small U over the 90-day radar history, fuse/cells has the evaluation window only (P6, #57); fuse.run's pure path can't compute U without detectors (tach); p6 config keys not in config.yaml yet (P1, #123); post_storm missing from coverage/exposure (P3, #85); slow presence-hours source on real data (P4, #131); P6 tests not in pytest testpaths (P1) |
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
