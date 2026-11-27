# Status

One line per module, updated at every merge. Format: what works on the simulator · what works on real data · what's blocked.

| Module | Simulator | Real data | Blocked |
| --- | --- | --- | --- |
| P1 core, sim, validate, CI | — | — | — |
| P2 ingest | — | — | — |
| P3 reference, coverage | — | — | — |
| P4 detect, match | — | — | — |
| P5 aggregate, forecast | — | — | — |
| P6 detectors, fuse | mid-p + BH, weekly Gi*, Poisson CUSUM (h = 0.5 from the simulator null) fill fuse/cells for the evaluation window (#54); context, fusion and fuse/ still stubs (#24) | — | p6 config keys not in config.yaml yet (P1) |
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
