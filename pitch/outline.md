# NarcoPolo pitch outline (3 minutes)

Draft from the six steps in `docs/specs/P7.md`. The Judging scorecard's pitch plan replaces this list
if it differs. Every number on a slide is read from the real `snapshot.json` (banner reads "real"), never
typed from memory. Wording rule: "unusual", "worth checking", "consistent with a drop-off". Never say
"smuggling detected". No vessel or person is named anywhere.

| # | Step | About | What is on screen | Say |
| --- | --- | --- | --- | --- |
| 1 | The problem | 25 s | One map of the south-west coast | Two or three ships watch 437,500 km². Drop-offs at sea are the main route for cocaine into Europe, and a patrol can only be in one place. |
| 2 | The idea | 20 s | The drop pattern: a large ship slows, small boats visit later | Find the drop, not the boat. Pick-ups can happen between satellite passes, so we watch the place where the ship slows, and what shows up near it afterwards. |
| 3 | Live demo | 60 s | Dashboard: one site, its reasons, its piers, the plan | Pick the top site. Read its reasons. Show the piers worth checking and the ship route and the aircraft sweep. Show one blind spot hatched grey: "we did not look here, so we say nothing". |
| 4 | The proof | 40 s | Validation panel | Chance of seeing a boat by size and sea state; forecast skill; how often we raise an alarm on pure noise; the five traps we designed out (unobserved is not zero, no look-ahead, places not people, calm passes only, honest intervals). |
| 5 | The limits | 20 s | One slide, plain words | Pick-ups between passes are missed; small boats in rough seas are missed; we point at places worth checking, not at people. About 5 days behind real time because of data delays. |
| 6 | Galileo | 15 s | One slide | Only if the organisers confirm it fits (unverified idea): authenticated Galileo signals (OSNMA) could give patrol evidence a trustworthy position and time. |

## Before the pitch

- [ ] Banner on every screenshot says what the data is (simulated, real or mixed). Pitch only from the real snapshot.
- [ ] Rehearse once with Wi-Fi off. The dashboard makes no network requests.
- [ ] Open the pywebview window on the presenting machine in advance; if it does not start, use the browser fallback (`uv run python -m dashboard.app` opens it automatically).
- [ ] Record the 90-second screen capture fallback by Sunday 10:00.
- [ ] Items still marked "not available yet" on the dashboard (observed versus expected, pier score) are either filled by then or named as next steps. Do not hide them.
- [ ] Read every number on a slide against `validation` in the snapshot.

## Open questions for the team

- Does the Judging scorecard's pitch plan change the order or the time per step?
- Is the Galileo slide confirmed with the organisers?
