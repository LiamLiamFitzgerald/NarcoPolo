# NarcoPolo pitch outline (3 minutes)

Positioning from #323 (part of #312). The Judging scorecard's pitch plan replaces this order if it differs.

Rules for every slide:
- Every number is read from the real `snapshot.json` (the banner reads "real") or from a cited source, never typed from memory. A `[snapshot: …]` tag names the field to read; a `[source: …]` tag names the document to cite.
- Wording: "unusual", "worth checking", "consistent with a drop-off". Never "smuggling detected", "detected", "suspect vessel" or a claim that a site is certain.
- No vessel or person is named anywhere.

## The pitch in three sentences

> Ireland watches 437,500 km² of sea with one or two ships a day. Free satellite services show where boats were; NarcoPolo tells that one ship where to go this week, explains every choice in plain words, and learns from each patrol. It runs on a laptop from open data, scores places not people, and supports both drug interdiction and fisheries protection from one plan.

## Running order

| # | Step | About | What is on screen | Say |
| --- | --- | --- | --- | --- |
| 1 | The decision | 20 s | Title, then the three sentences | The Joint Task Force tasks one ship a week. The hard question is not "what did the satellite see" but "where does the ship go". |
| 2 | Who else is out there | 20 s | Competitor slide (below) | The others show where boats were. None of them hands an Irish crew a ranked, explained weekly plan within its ship budget. |
| 3 | Live demo | 70 s | Dashboard, offline, in this order (below) | Read the screen, not a script. |
| 4 | Why you can trust it | 30 s | Claims table, one line per claim, with the evidence shown live | Each claim points at something on screen or in the validation panel. |
| 5 | What we can't see | 20 s | "What we couldn't see" screen | Pick-ups between passes and small boats in rough seas are missed. We say so on the map, hatched, instead of guessing. |
| 6 | Business and next steps | 20 s | Business model slide | Open core, paid deployment; one licence per agency. Say the GFW licence risk out loud. |

The Galileo slide (authenticated Galileo signals, OSNMA, for trustworthy patrol position and time) goes in only if the organisers confirm it fits. Otherwise it is a one-line "next step" on slide 6.

## Demo order (step 3)

1. **This week home.**
   - Read the question "Where should the ship and aircraft go this week?".
   - Read the figures row. `[snapshot: meta.figures]`
   - Flip the lens switch from Drop-off to Fisheries and back. Fisheries says "not available yet" until P3/P5/P6 deliver it (#320, #321). Say that, don't hide it.
2. **One site card.**
   - Take the first card, "Top of this week's shortlist". Read its one-line reason and "Why, in detail".
   - Press "Show on map".
   - Say "top of this week's shortlist", never anything firmer: site flags are off until #269.
3. **The plan.**
   - Show the ship route and the aircraft sweep, with hours used out of the budget. `[snapshot: plan]`
   - Show the mission mix once #316 lands; until then, show the stop list.
4. **The unobserved layer.**
   - Switch to "Blind spots" and point at a hatched cell: "We did not look here, so we say nothing."
   - On a radar pass that caught a small boat, show "follow-up unobserved" on the others.

## Competitors (step 2)

Check each line against the product's own public page before the pitch, and cite it on the slide. `[source: product page, date checked]`

| Service | What it gives an Irish agency | The gap NarcoPolo fills |
| --- | --- | --- |
| Skylight | Vessel alerts and tracks from AIS and satellite | No ranked weekly plan within one ship's hours |
| Global Fishing Watch | Open fishing-activity maps and dark-vessel layers | A map of where boats were, not where to send the ship |
| EMSA Copernicus Maritime Surveillance | Satellite imagery and vessel detections on request | Raw looks, not a plan, and not explained in plain words |
| Windward | Commercial maritime risk scores | Scores vessels; we score places, and run offline on open data |

## Claims and their evidence (step 4)

| Claim | Evidence we can show today |
| --- | --- |
| Decides, does not detect | The plan screen: a route within the ship and aircraft budget. `[snapshot: plan, meta.figures]` |
| Explainable by construction | Every site card has a one-line reason and "Why, in detail". `[snapshot: sites[].reasons]` |
| Honest about blind spots | Unobserved cells are hatched, never zero, and their tooltip says "No satellite look this week". `[snapshot: cells layer "unobserved"]` |
| Learns from patrols | The bandit updates from outcomes (`patrol/bandit.py`). Recording an outcome on screen needs #317. Until then, say "built, not yet wired to the screen". |
| Open data | Sources credited in the footer: Copernicus Sentinel, ERA5, Global Fishing Watch, OpenStreetMap. `[source: footer of the real snapshot]` |
| Light and sovereign | Runs on one laptop with Wi-Fi off; the dashboard makes no network requests (a test enforces it). |
| Ready for the EU AI Act, Article 14 | A human picks every patrol; the tool only ranks places and explains why. `[source: Regulation (EU) 2024/1689, Art. 14]` |
| Calibrated, not hopeful | Validation panel: chance of seeing a boat by size and sea state, forecast skill, false-alarm rate on pure noise. `[snapshot: validation]` |

If the validation panel says "Quick validation" (`[snapshot: validation.mode]` is "quick", #370), say "a quick run, not the full result" and never quote its numbers as the full validation.

## Scenario fixes (Daniel's scenarios)

- **The customer is the Joint Task Force.** It tasks the ship; NarcoPolo hands it the weekly plan.
- **Radar misses small boats; say so.**
  - Sentinel-1 misses most vessels under 15 m. `[source: cite the detection study used by P4]`
  - Read the simulator's pick-up count, and how many fell on a pass, from the validation output on the day. Do not quote a number from this outline. `[snapshot: validation]`
  - Show "follow-up unobserved" on the passes that saw nothing.
- **Keep the real context:**
  - the July 2025 Cork RIB seizure `[source: news report]`
  - Revenue's three piers on watch `[source: as given in the scenario]`
  - the Air Corps sweep (the aircraft line on the plan)
- **Fisheries is a main workflow, not an afterthought.** It has its own screen and lens; say what it needs to go live (#320, #321).

## Business model (step 6, to test with mentors)

- **Open core, paid deployment:** the model and dashboard are open; set-up, data feeds and support are paid.
- **One licence per agency.** Expansion via EMSA, MAOC-N and EFCA.
- **Risk, said out loud:** the Global Fishing Watch API is licensed for non-commercial use. A paid deployment needs either a GFW agreement or another AIS source (see the AIS source issue under #312).

## Before the pitch

- [ ] The banner on every screenshot says what the data is (simulated, real or mixed). Pitch only from the real snapshot.
- [ ] Every `[snapshot: …]` and `[source: …]` tag is replaced on the slide by the value or citation, read on the day.
- [ ] Rehearse once with Wi-Fi off, within 3 minutes.
- [ ] Open the pywebview window on the presenting machine in advance. If it doesn't start, use the browser fallback (`uv run python -m dashboard.app`).
- [ ] Print the Friday briefing (Print button) as the leave-behind page.
- [ ] Record the 90-second screen capture fallback by Sunday 10:00.
- [ ] Anything the dashboard marks "not available yet" is named as a next step, not hidden.

## Open questions for the team

- Does the Judging scorecard's pitch plan change the order or the time per step?
- Have the organisers agreed the Galileo slide fits?
- Which detection study does P4 cite for the Sentinel-1 small-boat limit?
