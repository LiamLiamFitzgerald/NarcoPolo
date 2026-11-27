# Status

One line per module, updated at every merge. Format: what works on the simulator · what works on real data · what's blocked.

| Module | Simulator | Real data | Blocked |
| --- | --- | --- | --- |
| P1 core, sim, validate, CI | — | — | — |
| P2 ingest | — | — | — |
| P3 reference, coverage | — | — | — |
| P4 detect, match | — | — | — |
| P5 aggregate, forecast | Full stage runs on a stand-in simulator (core/sim placeholders): observed, EWMA, GLM + EB, NB intervals, fold 0 + backtest rows | — | #58 (lane bias, zero rates break backtest skill); core/, sim/, integration from P1 |
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
