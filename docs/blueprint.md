<!-- Generated from the Agent blueprint (rev 108, 27 Nov 2026). Do not edit here: change the blueprint, then regenerate. -->

# Agent blueprint

## How to use this blueprint

This tab is the single source of truth for every agent building the system. If anything here conflicts with code, a comment or another doc, this tab wins until a human changes it.

**Reading order for every agent, before writing any code:**

1. Mission and context (why the system exists)
2. Design principles (the decisions you must not undo)
3. Data journey and data dictionary (what flows where, in what shape)
4. Measures and the statistical methods index (what every number means)
5. **Your own module spec only** (P1–P7)
6. Agent workflow and the failure catalogue

**Hard rules. Breaking any of these is a failed task, even if tests pass:**

- Touch only files inside your module's folder, plus your own tests. Never edit `core/` unless you are P1
- Read only the stage files listed as your inputs. Never read `raw/` unless you are P1 (validation only), P3 or P4
- Never invent a number, threshold, dataset name or API parameter. If this blueprint doesn't give it, add it to config with a `TODO(owner)` comment and open a GitHub issue labelled `question`
- Never store an unobserved cell as zero (see Design principles, rule 4)
- Never fit a model on data later than the training cut-off (rule 6)
- Never output a vessel name, number (MMSI), call sign or a person's name anywhere
- Every function you write gets a test against the simulator before you touch real data
- After three failed CI fix attempts on the same issue, stop, label the issue `blocked`, write what you tried, and wait for a human

**How to read the module specs:** each one has Purpose, Context (why it exists), Inputs, Outputs, Steps, Parameters, Resolved ambiguities (these override any looser wording above them), Warnings, Tests and Must not. Global settings apply to every module. Warnings are written as blockquotes; each one names a failure that produces **plausible-looking wrong results**, which tests may not catch. Read every warning in your module before you start.

**Words used in this blueprint:**

- **Must** = required; **should** = default unless a test shows a better choice; **may** = optional stretch
- **Simulated** = data from P1's simulator with known truth; **real** = data from P2
- **Default** = a starting value kept in `config.yaml`, to be tuned on the simulator or injection tests, never on the known Irish cases

## Judging scorecard (official criteria, 27 November)

The organisers' criteria, what full marks looks like, our evidence, and the actions that close each gap. Humans read this section; agents can skip it. Owners and deadlines are binding.

### Two findings that change the positioning

- **Detection is already funded in Ireland.** In February 2026 the Minister announced €1.8 million for two security projects, including Sea Scan, a Trinity College project giving the Naval Service an AI-enhanced real-time vessel detection system ([Irish Times](https://www.irishtimes.com/ireland/2026/02/25/ireland-should-not-fear-asking-allies-for-military-help-says-minister/)).
- **Detection is already free across the EU for authorities.** EMSA's Copernicus Maritime Surveillance service gives authorised customs, law-enforcement and security users vessel detection from satellite images, free of charge ([EMSA](https://emsa.europa.eu/copernicus/cms-cases/download/8437/5618/23.html)).

So we do not pitch as a boat detector. **We pitch the layer after detection: it turns anyone's detections (ours, Copernicus Maritime Surveillance, Sea Scan) plus AIS into drop sites, the piers they feed and a patrol plan.** Our own detector stays, because it lets the demo run on open data, but the product's value doesn't depend on it.

### Criteria map

| Criterion | Full marks looks like | Our evidence | Gap → action (owner, deadline) |
| --- | --- | --- | --- |
| 1.1 Link with the challenges | Directly answers "countering transnational crime and terrorism with space data" | Cocaine drop-offs at sea are the transnational route into Ireland; output is patrol action | Open the pitch with the challenge title word for word (P7, pitch draft Sat 18:00) |
| 1.2 EU space data and signals | Copernicus at the core, and a credible use of Galileo/EGNOS | Sentinel-1 radar (Copernicus) and ERA5 weather (Copernicus Climate Change Service) drive every score | Show a slide naming each EU source and what it does. Galileo: patrol plans export as waypoints, and OSNMA-authenticated position and time stamp the boarding evidence (roadmap, not built). Say GFW is replaceable by Copernicus Maritime Surveillance data for authorised users (P7) |
| 2.1 Customer problem | A named user with a quantified pain | Naval Service and Air Corps: 2–3 ships for 437,500 km²; Ireland's first National Maritime Security Strategy names drug interdiction and maritime surveillance as Naval Service tasks ([gov.ie](https://www.gov.ie/en/department-of-defence/press-releases/minister-mcentee-launches-first-ever-national-maritime-security-strategy)) | Interview at least 2 mentors or organisers in role ("you're a patrol planner") by Saturday 16:00; quote one line in the pitch (P2, after ingest is cached) |
| 2.2 Value creation | A before/after the judge can picture | Today: search the sea. With us: a weekly top 3 and a route | One number: share of patrol hours spent on flagged places vs a random plan on the simulator (P7, Sat 22:00). Keep it labelled "simulated" |
| 2.3 Technical inventiveness | Something reviewers haven't seen | Find the drop, not the boat: the ship-slowdown → small-boat lag link, sea-route piers, "unobserved is not zero", a null test proving we don't flag noise | One slide, one diagram of the lag link; show the null test result (P6 + P7) |
| 2.4 Business viability | Buyer, price logic, costs, channel, competition, licences | Data is free; compute is small | Use the business model below; one slide (P2) |
| 3.1 Technical expertise | The team clearly built it | 7 modules, tests, validation report | Live demo, plus the validation panel on screen (P1, P7) |
| 3.2 Business expertise | Someone owns the business case | — | P2 becomes business lead once ingest is cached (Sat 12:00) |
| 3.3 Commitment | A credible next step after Sunday | — | Roadmap slide: CASSINI mentoring, a pilot request to the Naval Service, a licence conversation with GFW (P2) |
| 3.4 Pitch quality | 3 minutes, one story, a live demo that cannot fail | 90-second backup video | Two full rehearsals with a timer, Sunday 11:00 and 13:00; one question-and-answer drill (all) |

### Business model (for 2.4 and 3.2)

| Item | Answer |
| --- | --- |
| Buyer | Irish Department of Defence for the Naval Service and Air Corps; Revenue's maritime customs and the Joint Task Force on drug interdiction as co-users |
| Next buyers | Other EU coastal states' navies, coast guards and customs, reached through the Copernicus Maritime Surveillance user community |
| Second use (same model, no new build) | "Unexplained small-boat activity" for fisheries protection; also a Naval Service task |
| Product | A weekly briefing: top 3 drop sites, piers to watch, a ship route and an aircraft sweep, with reasons and a validation report |
| Price logic | Annual subscription per coastline, priced well below the running cost of one wasted patrol day. Don't name a figure unless the team checks a source |
| Costs | Copernicus data is free; compute is a few cloud hours a week; the main cost is analyst time for onboarding |
| Channel | Public pilot funded like Sea Scan, then procurement; EU route via CASSINI and Copernicus Maritime Surveillance users |
| Competition | Detection: EMSA Copernicus Maritime Surveillance, Sea Scan, Skylight, GFW. Commercial maritime analytics: Windward, Kpler. None of these, as far as we found, ranks drop sites and piers from slowdown–visit links. Position them as data sources, not rivals |
| Licence risk | GFW data is non-commercial only. Pilot under a GFW custom licence or swap GFW for Copernicus Maritime Surveillance or commercial AIS; Sentinel-1 and ERA5 are open |
| Ethics | Places, not people: no vessel or person identities leave the pipeline |
| After Sunday | Winners get a six-month CASSINI mentoring programme with 100 hours of expert mentoring ([cassini.eu](https://www.cassini.eu/hackathons/7th-cassini-hackathon-winners)); then apply to the CASSINI Business Accelerator |

### Pitch plan (3 minutes)

| Time | Slide | Criterion |
| --- | --- | --- |
| 0:00–0:20 | The challenge, word for word, and the problem: 2–3 ships for 437,500 km² | 1.1, 2.1 |
| 0:20–0:40 | Detection exists (Copernicus Maritime Surveillance, Sea Scan). What's missing is where to send the ship | 2.1, 2.3 |
| 0:40–1:00 | The idea: find the drop, not the boat (lag-link diagram) | 2.3 |
| 1:00–1:50 | Live demo: one site, its reasons, its piers, the route | 2.2, 3.1 |
| 1:50–2:10 | Proof: recall by boat size, forecast skill, null test, the five traps designed out | 2.3, 3.1 |
| 2:10–2:30 | EU space data: Sentinel-1, ERA5, Galileo OSNMA for evidence | 1.2 |
| 2:30–2:50 | Business: buyer, second use, costs, licence path, competitors as sources | 2.4, 3.2 |
| 2:50–3:00 | Team and next step: mentoring, pilot request | 3.3 |

Limits (pick-ups between passes, small boats in rough seas, about 5 days behind) go in the question-and-answer answers, not the 3 minutes.

> Warning: never show a simulated result as real, and never quote a price, a pilot or a customer conversation that didn't happen. Judges ask; a caught overstatement costs more than the claim gains.

## Mission and context

**We build a system that tells Ireland's Naval Service and Air Corps which few offshore spots and piers to check this week for cocaine drop-offs, using free EU satellite data and honest uncertainty.**

### The competition

- 12th CASSINI Hackathon, "EU Space for Peace and Resilience", 27–29 November 2026; Ireland site run by the National College of Ireland in Dublin. Submission deadline Sunday 15:00
- Our challenge: Challenge 3, "Countering transnational crime and terrorism with space data". Solutions must use EU space assets (Copernicus, Galileo)
- Past editions required **fresh code only**: all code written by the team during the weekend ([8th edition rules](https://taikai.network/en/cassinihackathons/hackathons/euspace-defence-security/rules)). Libraries and public data are fine
- Past winners each solved one sharp problem for a named user; in the 2024 security edition two of the three winners tackled GNSS problems (navigating drones without GNSS; detecting GNSS spoofing)

### How cocaine actually reaches Ireland by sea

- **The drop-off is the main method.** A large ship drops a consignment overboard and a smaller "daughter" vessel, usually a fishing boat or pleasure craft, collects it and takes it ashore ([Irish Times](https://www.irishtimes.com/crime-law/2023/08/05/ireland-is-awash-with-cocaine-how-does-it-get-here-and-what-is-being-done-to-stop-the-supply)). A 2026 Frontex operation confirmed dropping drugs from cargo ships for small boats to collect is the most used method into Europe ([Marine Insight](https://www.marineinsight.com/14-countries-unite-in-operation-white-sea-vi-to-seize-454-kg-of-cocaine-in-european-waters/))
- **Pick-up can be much later.** Bales have been dropped up to 20 km offshore, sunk with a GPS tracker and timed or triggered floats ([Irish Examiner](https://www.irishexaminer.com/news/munster/arid-+41354149.html)); sources describe designated drop positions off the Irish coast ([Irish Examiner](https://www.irishexaminer.com/news/arid-41365204.html?type=app))
- **The mothership is a legitimate cargo ship** with corrupt crew paid up to €200,000 ([TheJournal](https://www.thejournal.ie/article.php?id=6789400))
- **The daughter boat blends in:** a local fishing boat, yacht or RIB returning to a quiet coast or small marina ([Windward](https://windward.ai/?p=53006)). Real Cork landings: Broad Strand into a waiting van ([Irish Examiner](https://www.irishexaminer.com/news/munster/arid-41662508.html)); Tragumna Pier ([RTÉ](https://www.rte.ie/news/regional/2025/0722/1524709-cork-drugs-court))
- **Weather and timing break operations:** a Cork drop could not be retrieved due to weather; a fast boat from West Cork missed its rendezvous with a cargo ship off Cornwall
- The MV Matthew pick-up boat, the Castlemore, was a 14.9 m fishing boat bought weeks before ([Irish Times](https://www.irishtimes.com/crime-law/2023/09/29/irelands-biggest-cocaine-haul-how-the-plan-ran-aground)), just under the 15 m AIS line

### The fishing fleet (our "normal")

- EU fishing vessels over 15 m must carry AIS; 12 m and over carry VMS; under the 2023 revised control rules (Regulation (EU) 2023/2842), boats under 12 m may carry a portable device and boats under 9 m can be exempted until the end of 2029 ([Outlaw Ocean summary of EU rules](https://theoutlawocean.com/toolkit/global-fishing-legislation/european-union/vessel-tracking))
- 1,164 active Irish boats are under 12 m, 84% of the active fleet ([The Skipper](https://theskipper.ie/?p=23775)). **AIS misses most real fishing**
- BIM has validated maps of where under-12 m boats fish off the south coast ([The Skipper](https://theskipper.ie/bim-maps-where-inshore-boats-fish/)); the Marine Institute publishes inshore activity layers

### Enforcement

- Two ships patrol at a time, sometimes three ([Irish Examiner](https://www.irishexaminer.com/news/spotlight/arid-41822300.html)), for 437,500 km² of Irish waters. Naval ships are typically sent to investigate ships spotted by the Air Corps' two maritime patrol aircraft

### The satellites and what they can see

- **Sentinel-1** is a C-band radar (microwave): works day, night and through cloud. The image is greyscale backscatter; colour only exists in false-colour composites
- IW mode GRD high resolution: about 20 × 22 m true resolution with 10 m pixel spacing, about 250 km swath. **A small boat is a bright blob of a few pixels**
- Revisit over Europe roughly every 1–3 days; images are **snapshots, not tracks**. Sentinel-1B ended in December 2021; Sentinel-1C data has been available since early 2025, so coverage density changes over time
- Rough seas hide small boats; bright ships cause faint "ghost" copies; wind turbines and buoys look like boats

### What we build

AIS shows large ships pausing where they shouldn't; radar shows small boats visiting the same spot later; inshore maps say whether that is normal; piers within reach say where it lands. **We find the drop, not the boat.** The output is a weekly top 3 of drop sites and piers, a patrol route for a ship, a sweep for an aircraft, and the evidence for each, with its uncertainty.

## Design principles

Thirteen decisions shape everything below. Agents must not undo them; a human may, by editing this section.

| # | Principle | Why |
| --- | --- | --- |
| 1 | **Find the drop, not the boat.** Score recurring offshore drop sites (a large ship pauses, small boats visit later), not individual boats | Pick-ups can happen within hours, between satellite passes, so most are never imaged. The ship half is in AIS, which is continuous |
| 2 | **Forecast normal, flag the surprise.** Every score is observed versus expected | There are almost no labelled smuggling events. "Suspicious" can't be measured; a forecast can be backtested |
| 3 | **Weak evidence adds up.** Each detection carries a probability; counts are sums of probabilities | Small boats are the core target and no single small detection is certain at 20 m resolution |
| 4 | **Unobserved is not zero.** Every count travels with its exposure; no pass means exposure 0 | Storing "not seen" as "0 boats" makes quiet cells look empty and busy ones suspicious, silently |
| 5 | **Small boats only on calm passes.** Rough passes count as unobserved for small boats | Waves hide small boats; a storm would otherwise look like an empty sea |
| 6 | **No look-ahead.** Fitting only sees data before the cut-off, with a 7-day gap before testing | Leakage makes backtests look excellent and mean nothing |
| 7 | **Statistics first, models only if they win.** A model stays only if it beats the statistical baseline in the walk-forward backtest | Statistical methods are fast, explainable and need no labels; a weekend leaves no time to debug an unexplainable model |
| 8 | **Several cheap detectors, read as angles, not votes.** Size, neighbourhood, build-up, context | Each catches a different kind of surprise, and the mix gives reasons; they share the same counts, so agreement is not independent evidence |
| 9 | **Normal fishing comes from inshore maps, not AIS** | Most boats are under 12 m and carry no AIS |
| 10 | **Places, not people.** No vessel or person identities in any output | Most small-boat crews are honest workers; naming suspects in a public demo is unfair and risky |
| 11 | **Measure our own honesty.** Recall by boat size, injection tests, null test, calibration. Known Irish cases are a sanity list, never tuning data | Judges and users need to know how often we miss; tuning on five cases then claiming they validate us is circular |
| 12 | **One-way data flow through checked contracts; simulator first** | A bug can only spoil its own output, and every part can start before real data exists |
| 13 | **Few, explained, explorable outputs.** A weekly top 3, an aircraft sweep, and one exploration visit | 2–3 ships for 437,500 km². Only ever patrolling the top-ranked places makes the system confirm itself, the known flaw of predictive policing |

**Language rule for every output:** say "unusual", "worth checking" or "consistent with a drop-off". Never say "smuggling detected".

## Global settings

These values were missing from the first version and every module needs them. They live in `config.yaml`; no module hardcodes them.

| Key | Default | Meaning |
| --- | --- | --- |
| `region_bbox` | lon −10.6 to −7.9, lat 51.1 to 51.95 (roughly Dursey Head to Ballycotton, with room for 25 km offshore south of Mizen Head; my approximation) | Outer box; the working region is the sea inside it within 25 km of the coast. TODO(P3): trim to where inshore maps exist |
| `x0`, `y0` | The region's minimum UTM x and y, rounded **down** to a multiple of 10,000 m | Grid origin, so 2 km cells nest exactly in 10 km cells |
| `T` (snapshot date) | The last full UTC day with radar data | Everything is computed as of this day |
| Evaluation window | From the Monday of the ISO week three weeks before T's week, up to T (22–28 days), so it matches the 4 weeks the dashboard shows | Days that get scored and shown |
| Ship history | T − 729 to T (24 months) | Slowdowns and AIS-derived layers |
| Radar history | T − 89 to T (90 days) | Small-boat detections |
| Week | ISO week, Monday to Sunday, UTC | Dashboard shows the week containing T and the 3 before |
| `base_port` | Haulbowline, Cork Harbour (Naval Service base) | Start and end of the ship route |
| `seed` | 20261127 | Global seed; each use derives its own as seed + a fixed per-use number written next to it in config |
| Units | metres, seconds, UTC; knots only in config and in raw AIS speeds, converted on read with 1 kn = 0.514444 m/s | No other units in code |

## Data journey

Data moves one way: each stage reads only the files above it and writes one file of its own, so a bug can only spoil its own output and everything downstream of it.

&#91;embedded content: data journey · 9 stages, 2 side inputs\]

Coverage feeds calm passes to detection and exposure to the counts; reference feeds the static mask to detection, covariates to the forecast, and pier travel times to the drop sites. P1's validation reads every stage but writes only reports.

### What the data looks like at each step

| Step | One row (or pixel) is | Shape (approx.) | What changes |
| --- | --- | --- | --- |
| 1. Raw inputs | A radar pixel (VV, VH); an AIS ping; a GFW grid cell-day; an ERA5 grid point-hour | \~30 scenes of 15,000 × 2,500 px × 2; AIS and GFW tables | Nothing interpreted: files as delivered, cropped |
| 2. Detections | One radar candidate on one pass | tens to hundreds per pass | Pixels become blobs with features and a probability `p_boat` |
| 3. Events | One `dark_small` boat or one ship `slowdown` | thousands | Matched boats removed; AIS turned into slowdown events; identities hashed |
| 4. Observed | One 2 km cell × one UTC day × one event type | \~770k rows | Events become soft counts C, paired with exposure E; unobserved rows kept as E = 0 |
| 5. Expected | Same grain as Observed | \~770k rows | Adds μ (normal), φ (dispersion), 90% interval, from training data only |
| 6. Cell scores | Same grain, observed rows only | ≤ 770k rows | Adds the four detector scores, U and the agreement badge |
| 7. Drop sites | One cluster of ship slowdowns | tens | Slowdowns linked to later small-boat surprises; S, permutation p-value, recurrence, top piers, reasons |
| 8. Plan + snapshot | One JSON document per week | < 5 MB | Top sites become routes; heat-map values and evidence frozen for display; identities scanned out |
| 9. Dashboard | Pixels on screen | — | Only drawing, sorting and formatting |

### Example journey of one drop

1. Tuesday 02:10: AIS shows a cargo ship slow from 13 to 2 knots for 40 minutes, 14 km off the coast, outside lanes and anchorages → a `slowdown` event (P4)
2. Its cell-day gets C = 1 against μ = 0.02 → high U for slowdowns (P5, P6)
3. Thursday 18:30: a calm Sentinel-1 pass sees a 3-pixel unmatched blob 2 km away with `p_boat` = 0.6 → a `dark_small` event; its cell-day has C = 0.6 against μ = 0.05 → high U for small boats
4. The lag link joins them (2.7 days apart, within 4 km) → L for that slowdown (P6)
5. Earlier slowdowns at the same spot cluster into one site; the permutation test says busy traffic alone rarely scores that high → `bh_flag` (P6)
6. Piers close by sea get most of the site's score (it decays with travel time) → two quiet piers rise in the ranking (P6)
7. The ship plan visits the site and lists its top pier for a shore check; the aircraft sweep includes it (P7)
8. The dashboard shows the site with its reasons, its badge and its route (P7)

## Data dictionary

Every stage file, its columns and the rules that must always hold. Positions are metres in EPSG:32629; times are UTC. Sizes are my estimates for a 150 × 25 km coastal band (about 3,750 km², about 940 sea cells at 2 km), 24 months of ship data and 90 days of small-boat radar.

### Raw inputs (`raw/`, written by P2)

| File | Contents | Approx. size |
| --- | --- | --- |
| `s1/<hash>.tif` | GeoTIFF, 2 bands (VV, VH), int16 = sigma0 in dB × 100, 10 m pixels, about 15,000 × 2,500 | \~150 MB each, \~30 scenes (25 calm, 5 rough) |
| `s1/<hash>.json` | scene id, start time, orbit direction, relative orbit, footprint (WKT), incidence angle min and max, and from the annotation XML: PRF (Hz), slant range (m), satellite speed (m/s), platform heading (heading\_deg) | small |
| `gfw_sar.parquet` | GFW SAR detections as returned (position, time, matched flag, any size estimate) | thousands of rows |
| `gfw_presence.parquet` | GFW AIS presence: grid cell, date, hours, speed bin | \~10⁵–10⁶ rows |
| `ais.parquet` (if a source is found) | ship id, time, position, speed over ground (knots), course (degrees), ship type code, length (m) | could be large; crop to region |
| `era5.nc` | hourly 10 m wind u and v (m/s), significant wave height (m), 0.25° grid | small |
| `osm_piers.geojson`, `coastline.gpkg`, `inshore/*.gpkg`, `infomar_bathy.tif` | static layers as downloaded | small |
| `manifest.json` | per file: request, hash, download time, licence | small |

### Stage files

| File (writer) | Columns: type, unit | Approx. rows |
| --- | --- | --- |
| `reference/layers.gpkg` cells layer (P3) | `cell_id` str; `level` int (2000 or 10000); `geometry` polygon; `inshore_frac` `float 0–1, or NaN where no inshore map exists; lane`, `anchorage`, `port_zone`, `exclusion` bool; `dist_coast_m` float; `static_frac` float 0–1; sea\_frac float 0.2–1 | \~1,000 |
| `reference/layers.gpkg` piers layer (P3) | `pier_id` str; `name` str; `geometry` point; `road_access` bool | tens |
| `reference/layers.gpkg` land layer (P3, #133) | `id` int; `geometry` (multi)polygon, EPSG:32629: the land P3 closes from the coastline lines (land on the left, as in OSM); read by P7 for the basemap | 1 |
| `reference/sea_250m.tif` (P3) | uint8: 1 sea, 0 land | about 750 × 380 px (the whole bounding box, land included) |
| `reference/travel_hours.parquet` (P3) | `cell_id`, `pier_id`, `hours` float | cells × piers, \~50k |
| `coverage/exposure.parquet` (P3) | `cell_id`, `pass_id`, `time_utc`, `covered_frac` 0–1, `wind_ms`, `hs_m`, `calm` bool, `exposure_small` float 0–1 | \~60 passes × \~940 cells, \~56k |
| `detect/detections.parquet` (P4) | `det_id`, `pass_id`, `time_utc`, `x_m`, `y_m`, `peak_ratio_vv_db`, `peak_ratio_vh_db`, `pol_agree` bool, `n_px` int, `size_class` {small, medium, large}, `ghost` bool, `p_boat` float 0–1 | tens to hundreds per pass |
| `match/events.parquet` (P4) | `event_id`, `event_type` {dark\_small, slowdown}, `time_utc`, `x_m`, `y_m`, `cell_id`, `p` float 0–1, `duration_min` (slowdowns), `ship_key` (salted hash, internal only), `matched` bool | thousands |
| `aggregate/observed.parquet` (P5) | `cell_id`, `level`, `date`, `event_type`, `count` float ≥ 0, `exposure` float ≥ 0 | \~690k slowdown + \~85k small, \~770k |
| `forecast/expected.parquet` (P5) | `cell_id`, `date`, `event_type`, `mu` float, `phi` float, `lo90`, `hi90`, `model` str, `fold` int | same as observed |
| `fuse/cells.parquet` (P6) | `cell_id`, `date`, `event_type`, `p_mid`, `bh_flag` bool, `gi_z`, `cusum_s`, `context` 0–1, `U` 0–1, `agreement` 0–4 | same as observed, observed rows only |
| `fuse/sites.parquet` (P6) | `site_id`, `x_m`, `y_m`, `n_slowdowns`, `S` float, `p_perm`, `bh_flag` bool, `recurrence` int, `followup_unobserved` int, `agreement` 0–4, `reasons` list\[str\], `top_piers` list\[str\] | tens |
| `patrol/plan.json` (P7) | per asset: ordered stops (site or pier id, arrival time, dwell) | small |
| `export/snapshot.json` (P7) | see P7 | < 5 MB |

`fuse/cells.parquet` is new compared with the Plan tab: the dashboard's heat maps need per-cell scores, and P6 already computes them. P3 also writes reference/land\_mask\_10m.tif and reference/static\_mask\_10m.tif (uint8, 1 = masked, on the same 10 m grid as the radar crops); P4 reads both.

### Invariants (checked by `core` schemas on every read and write)

- `exposure ≥ 0`; if `count > 0` then `exposure > 0`; rows with `exposure = 0` have `count = 0` and are never used in a fit or a score
- Every `cell_id` exists in `reference/layers.gpkg`; every `time_utc` is timezone-aware UTC
- All probabilities are in \[0, 1\]; `U` in \[0, 1\]; `agreement` in 0–4
- No column after `match/` holds a raw ship identifier. `ship_key` is a salted hash and never leaves `match/` and `fuse/`
- File-level: each stage file carries the config hash and simulator seed (or `real`) it was built from, so stale files are detected

## Measures

Every quantity the system computes, in the order data meets it. Agents must use these names in code and column names.

| Symbol | Name | Formula (plain) | Unit | What it means | Made in |
| --- | --- | --- | --- | --- | --- |
| `p_boat` | Detection probability | Logistic model on detection features, trained on injected boats | 0–1 | Chance a radar candidate is a real boat | P4 |
| `p` (slowdown) | Event probability | 1.0 from AIS | 0–1 | AIS events are treated as certain | P4 |
| C | Soft count | Sum of `p` over events in a cell, day, type | boats | Expected number of real events seen | P5 |
| E | Exposure | Small boats: covered sea fraction × calm, summed over passes in the day. Slowdowns: sea\_frac per day | passes or days | How much we actually looked | P3, P5 |
| r̂ | Baseline rate | Decayed sum of C ÷ decayed sum of E (EWMA) | events per unit exposure | Normal rate for this cell | P5 |
| μ | Expected count | E × exp(xβ) × θ̃ (regression) or E × r̂ (EWMA) | boats | What normal looks like here, today | P5 |
| φ | Dispersion | Pearson χ² ÷ degrees of freedom | none | How much more variable counts are than Poisson | P5 |
| θ̃ | Shrunk cell multiplier | (a + O) ÷ (a + M) | none | How much busier this 10 km cell is than the model says, pulled towards 1 when evidence is thin | P5 |
| z | Pearson residual | (C − μ) ÷ √(max(φ, 1) · μ) | standard deviations | Surprise in comparable units | P6 |
| `p_mid` | Mid-p tail value | P(X > c) + ½ P(X = c), X negative binomial | 0–1 | Chance of this many or more under normal | P6 |
| `bh_flag` | False-discovery flag | Benjamini–Hochberg at q = 0.1 | yes/no | Unusual after correcting for testing many cells | P6 |
| y | Stabilised ratio | (C + 0.5) ÷ (μ + 0.5) | none | Observed over expected, safe at small counts | P6 |
| `gi_z` | Gi\* z-score | Getis-Ord local statistic on y | standard deviations | This cell and its neighbours are high together | P6 |
| `cusum_s` | CUSUM statistic | max(0, previous + z − 0.5) | none | Slow build-up over days | P6 |
| `context` | Context score | Mean of yes/no facts (see P6) | 0–1 | Unusual for its setting | P6 |
| U | Unusual score | Mean of the four detectors' percentile ranks | 0–1 | Overall unusualness of a cell on a day | P6 |
| `agreement` | Agreement badge | Count of detectors with the cell in their top 10% | 0–4 | How many angles agree | P6 |
| X | Follow-up exposure | Small-boat exposure near a slowdown in the next 7 days | passes | Could we have seen a pick-up at all? | P6 |
| L | Link score | U of the slowdown × best later U of nearby small boats × time decay | 0–1 | Slowdown followed by a small-boat visit | P6 |
| S | Site score | Sum of L with a 30-day half-life | none | How strongly a spot behaves like a drop site, recently | P6 |
| `p_perm` | Permutation p-value | Share of time-shuffled runs scoring at least as high | 0–1 | Could busy traffic alone explain this site? | P6 |
| `recurrence` | Recurrence count | Distinct linked slowdowns above the median L | events | Is the spot reused? | P6 |
| T | Sea travel time | Sea-only distance ÷ boat speed | hours | How quickly a boat gets from a spot to a pier | P3 |
| P\_j | Pier score | Sum over sites of S × exp(−T ÷ 1 h) | none | Which piers to watch | P6 |
| skill | Forecast skill | 1 − model deviance ÷ flat-baseline deviance | ≤ 1 | Better than "same as average" if above 0 | P1 |
| recall | Detection recall | Detected ÷ present, by size and sea state | 0–1, Wilson 95% interval | How often we see a boat that is there | P1 |
| Brier | Brier score | Mean of (probability − outcome)² | 0–1, lower is better | Are probabilities honest? | P1 |
| false-flag rate | Null-test rate | Share of time-shuffled runs with at least one flagged site | 0–1 | How often we raise alarms on pure noise | P1 |

## Statistical methods index

Every method in the system, in data order. If an agent wants a method not on this list, it opens a `question` issue first.

| Method | Module | Purpose | Library | Key assumption | How it fails silently |
| --- | --- | --- | --- | --- | --- |
| Cell-averaging CFAR with guard ring | P4 | Find pixels brighter than local sea | `scipy.ndimage.uniform_filter` | Background ring is sea only | Coast or a nearby ship in the ring raises the background and hides boats |
| Gamma threshold from equivalent looks | P4 | Starting threshold for a false-alarm rate | `scipy.stats.gamma.isf` | Speckle is gamma-distributed | Real clutter has heavier tails: more false alarms than the formula says |
| Connected components (8-neighbour) | P4 | Group flagged pixels into candidates | `scipy.ndimage.label` | One boat = one blob | Two close boats merge; a long ship splits |
| Azimuth-ambiguity ghost rule | P4 | Remove radar ghosts of bright objects | own code | Offset formula and scene metadata are right | Wrong offset lets ghosts through as dark boats |
| Logistic regression calibration | P4 | Turn detection features into `p_boat` | `statsmodels` `Logit` or `scikit-learn` | Injected boats look like real ones | Too-bright injections make probabilities overconfident |
| Dawid–Skene EM (optional) | P4 | Combine 3+ detector views without labels | `crowd-kit` | Views make independent errors | Correlated views inflate confidence |
| Linear interpolation of AIS | P4 | AIS position at scan time | `numpy.interp` in UTM | Straight motion between pings | Long gaps put ships in the wrong place |
| Hungarian assignment with a gate | P4 | One-to-one detection–AIS matching | `scipy.optimize.linear_sum_assignment` | Gate wider than position error | Too tight: real AIS ships become "dark" |
| Rolling median speed, threshold rule | P4 | Ship slowdown events | `pandas` | Exclusion zones capture legitimate stops | Pilot boarding or weather stops become "suspicious" |
| Exposure-aware EWMA | P5 | First baseline rate | own code | Rate changes slowly | Treating unobserved days as zeros drags rates down |
| Quasi-Poisson regression with exposure offset | P5 | Covariate baseline | `statsmodels` `GLM`, `scale="X2"` | log-linear in covariates | Omitting the offset makes well-covered cells look busy |
| Empirical Bayes Gamma–Poisson shrinkage | P5 | Stabilise sparse cells | own code (moments) | Cell multipliers vary around 1 | Skipping it makes one stray boat look like a hotspot |
| Negative binomial predictive interval | P5, P6 | Ranges and tail probabilities | `scipy.stats.nbinom` | Variance = φμ | φ < 1 must fall back to Poisson |
| Walk-forward splits with 7-day embargo | P1, P5 | Honest backtest | own code (`core.Split`) | Future never informs the past | Any rolling feature computed on the full series leaks |
| Poisson deviance skill | P1, P5 | Compare forecasts | own code | Counts roughly Poisson | Very sparse folds give noisy skill: report ranges |
| Mid-p negative binomial tail | P6 | Per-cell surprise | `scipy.stats.nbinom` | μ and φ are right | A bad baseline makes everything "surprising" |
| Benjamini–Hochberg FDR | P6 | Control false flags over many tests | `statsmodels.stats.multitest` | Tests independent or positively dependent | Running it per subset instead of over the whole set |
| Getis-Ord Gi\* with permutations | P6 | Neighbourhood hotspots | `esda.G_Local(star=True)`, `libpysal` | Non-negative variable; weights skip unobserved cells | Unobserved cells treated as zero neighbours |
| CUSUM | P6 | Slow build-ups | own code | Residuals roughly standardised | Updating on unobserved days |
| Percentile-rank fusion | P6 | Combine detectors on one scale | `pandas.rank(pct=True)` | Ranks over the same set of cells | Ranking over different cell sets skews U |
| DBSCAN | P6 | Group slowdowns into sites | `sklearn.cluster.DBSCAN` | Distances in metres | Degrees instead of metres |
| Exponential time decay | P6 | Favour quick pick-ups and recent events | own code | Pick-ups follow within days | — |
| Circular time-shift permutation test | P1, P6 | Site significance; null test | own code | Shifting breaks timing but keeps busyness | Too few shuffles give unstable p-values |
| Minimum-cost path on a sea raster | P3, P7 | Sea-only distances | `skimage.graph.MCP_Geometric` | Land cost infinite | A gap in the coastline lets boats cross land |
| Greedy orienteering + 2-opt | P7 | Route within a time budget | own code | Travel times correct | Straight-line distances cut across headlands |
| Bootstrap and Thompson-style draw | P7 | Pick the exploration site | `numpy` | Resampled scores reflect uncertainty | Unseeded draws make the demo change every run |
| Wilson score interval | P1 | Recall uncertainty | `statsmodels` `proportion_confint` | Binomial counts | — |
| Reliability diagram and Brier score | P1 | Check probability calibration | own code or `sklearn.calibration` | Enough held-out events | Too few events per bin: merge bins |
| Injection test | P1 | Measure detection recall and false alarms | own code | Injected blobs resemble real boats | Adding in dB instead of linear power |

## Maps and heat maps

The dashboard shows **one heat map at a time** under a fixed set of overlays, for a selected week. Every value comes from `snapshot.json`; the browser computes nothing.

### Heat maps (pick one)

| Heat map | Value per 2 km cell | Source | Colour scale | Reads as |
| --- | --- | --- | --- | --- |
| Normal small-boat activity | μ ÷ E for `dark_small`, weekly mean | `forecast/expected` | Sequential, one hue, light to dark, quantile breaks | Where small boats usually are when we look |
| Observed versus expected | log₂(y) for `dark_small`, weekly | `fuse/cells` | Diverging around 0 (y = 1), grey midpoint, clipped at ±3 (8× more or less) | Busier or quieter than normal |
| Unusual score | Weekly max of U, either event type | `fuse/cells` | Sequential 0–1 | Where the detectors agree something is off |
| Blind spots | Summed small-boat exposure in the week | `coverage/exposure` | Sequential; zero exposure hatched | Where we could not see small boats at all |

### Overlays (always on, toggleable)

| Overlay | Drawn as | Size or style from |
| --- | --- | --- |
| Inshore fishing grounds | Thin outline | `inshore_frac` ≥ 0.1 |
| Shipping lanes, exclusion zones | Light hatch | `lane`, `exclusion` |
| Drop sites | Circles | Radius ∝ S; solid if `bh_flag`, hollow if not significant |
| Follow-up unobserved | Small open diamond at the slowdown | `followup_unobserved` > 0 |
| Agreement badge | Up to 4 dots beside a site or a cell with U ≥ 0.9 | `agreement` |
| Piers | Squares | Size ∝ P\_j; only `road_access` piers |
| Routes | Ship: solid line; aircraft: dashed line | `plan.json` |

### Rules for every map

> **Warning:** an unobserved cell must be drawn hatched grey, never in the lowest colour of the scale. Colouring it as "low" tells a patrol officer the sea was empty when we simply didn't look. This is the visual form of Design principle 4.

- Every heat map has a legend with units and the week shown
- The banner shows `data_label` (simulated, real or mixed) in every screenshot
- Diverging scales only for observed versus expected; everything else is one hue
- No vessel names or numbers in tooltips: sites show their reasons and numbers only

## P1 Core, simulator, validation

**Purpose:** the shared types every module depends on, fake data with known truth so every module can be built and tested before real data exists, the merge gate, and the independent checks that prove our numbers.

**Context:** this part makes several "silent" failures impossible by construction (unobserved-as-zero, look-ahead, mixed coordinates, schema drift, untested numbers). It is also the only part allowed to call other modules, and only to test them.

**Inputs:** none for `core` and `sim`; `validate` reads every stage file and may call modules' public functions.

**Outputs:** `core/` package; `sim/` package that writes files identical in shape to `raw/` and every stage file; `validate/` reports (`reports/validation.json`, read by P7); CI config; Tach config; `Makefile` with `fetch`, `all`, `sim`, `test`, `validate`.

### Steps: core types

1. `core.crs`: EPSG:32629 (UTM 29N, metres). One transformer, `pyproj.Transformer.from_crs(4326, 32629, always_xy=True)`, and its inverse for export
2. `core.grid`: `ix = floor((x − x0) / s)`, `iy = floor((y − y0) / s)`, `cell_id = f"{s}_{ix}_{iy}"`; s = 2000 (fine) and 10000 (coarse); parent of a fine cell = `(ix // 5, iy // 5)`. x0, y0 from config
3. `core.time`: only timezone-aware UTC timestamps; naive timestamps raise on read
4. `core.Observed`: a frame with `count` and `exposure`; rate defined only where exposure > 0. No module function accepts a bare count series
5. `core.Split(cutoff, embargo_days=7, test_days=7)`: `train()` = rows before cutoff; `test()` = rows from cutoff + embargo to + test\_days. `fit` functions take a `Split` and raise if any training row is at or after cutoff
6. `core.schemas`: one `pandera` schema per stage file, enforcing the Data dictionary's types, ranges and invariants; called on every read and write
7. `core.config`: loads `config.yaml`, returns a frozen object plus its SHA-256 hash, which every stage file stores

### Steps: simulator (one seeded function)

`simulate(config, seed)` writes `raw/` and every stage file for a synthetic region.

1. **Map:** a synthetic coastline, 6 piers (4 with road access), inshore grounds as polygons within \~5 km of shore, one shipping lane, one anchorage, one wind farm (static objects)
2. **Normal small boats** per cell c and day t, Poisson with rate

```latex
\lambda_c(t) = \exp\left(\beta_0 + \beta_1 \cdot \text{inshore}_c + \beta_2 \cdot \text{lane}_c + \gamma \sin(2\pi t / 365)\right)
```

3. **Normal ship slowdowns:** high rate in the anchorage and port zones, near zero elsewhere
4. **Planted drop site:** slowdowns at one offshore point (5–20 km out) about every 10 days; each followed with probability 0.8 by a small-boat visit after a delay drawn uniformly from 0.2 to 4 days
5. **Weather:** a daily wind and wave series with storms; on rough days, 70% of planted pick-ups are delayed to the next calm day
6. **Observation:** passes every 1–3 days covering part of the region; each true boat is detected with probability

```latex
p_{det} = \sigma(a + b \cdot L - c \cdot w)
```

(L length in m, w wind in m/s, σ the logistic function), plus false alarms at a fixed rate per km² and ghost copies of bright ships at the ambiguity offset

7. **Truth file:** `sim/truth.parquet` with every true boat, every planted drop and pick-up. Only `validate` may read it

### Steps: validation harness

| Check | Method | Pass when |
| --- | --- | --- |
| Recall curve | For every AIS vessel under 24 m inside a pass footprint at scan time, detected or not within 300 m. Bins: length < 8, 8–12, 12–15, 15–24 m × calm or rough. Wilson 95% intervals | Reported, with sample sizes; no pass/fail |
| Injection | Add a Gaussian spot (σ = 1 px) to **linear** sigma0 at random sea positions, brightness relative to local clutter; rerun P4 | Recall and false-alarm rate reported per brightness |
| Simulator recovery | Run the whole pipeline on the simulator | Planted drop site ranks 1st; planted rates recovered within 20% |
| Null test | Circularly shift each cell's event times by a random offset, 200 runs | Share of null runs with at least one flagged site ≤ about q (0.1) |
| Backtest | Walk-forward, 12 weekly folds for slowdowns and 6 for dark\_small, 7-day embargo | Skill > 0 for the chosen baseline |
| Calibration | Reliability diagram (10 bins) and Brier score on held-out folds | Reported; bins with < 20 events merged |
| Known cases | Castlemore (Sept 2023), Broad Strand, Tragumna Pier, washed-up bales | Shown in the pitch only; never used for tuning |

### Parameters (config)

`x0`, `y0`, region polygon; `embargo_days = 7`; `test_days = 7`; `n_folds_slowdown = 12; n_folds_small = 6`; simulator: `beta0..2`, `gamma`, drop interval 10 days, pick-up probability 0.8, delay 0.2–4 days, false-alarm rate, `seed`.

### Resolved ambiguities

- **Simulator defaults** (were unstated): β₀ = −4, β₁ (inshore) = 2, β₂ (lane) = 1, γ = 0.3; detection a = −4, b = 0.4 per metre, c = 0.5 per m/s; small-boat lengths uniform 6–15 m; false alarms 0.002 per km² per pass; 120 simulated days; same region size as the real one. At 10 m length and 3 m/s wind this gives p\_det ≈ 0.18; at 15 m and 2 m/s, ≈ 0.73
- **Fold definition:** fold k (k = 1 … K) tests days \[T − 7k + 1, T − 7k + 7\]; its cutoff is 7 days before the test start (the embargo). K = 12 for slowdowns, 6 for `dark_small`
- **Null-test pass rule:** with no true drop sites, Benjamini–Hochberg keeps the chance of *any* flag near q, so the check is the share of runs with at least one flag, not the share of flagged sites
- **`reports/validation.json` keys:** `recall` (rows: length\_bin, sea\_state, n, detected, recall, lo, hi), `injection` (rows: brightness\_db, recall, false\_alarms\_per\_km2), `skill` (rows: event\_type, model, mean, min, max), `calibration` (rows: bin\_lo, bin\_hi, n, mean\_pred, observed), `brier`, `null` (runs, share\_with\_any\_flag)

### Warnings

> **Warning:** `always_xy=True` is mandatory. Without it pyproj may swap latitude and longitude, and every distance is silently wrong.

> **Warning:** the simulator must never share code paths with the modules it tests (no importing P4's detector to make fake detections). Otherwise a bug appears in both and the tests pass.

> **Warning:** injected boats must be added in linear power, not dB. Adding in dB makes them far too bright and recall far too optimistic.

> **Warning:** the known Irish cases must never be used to tune a threshold. If a threshold is changed after looking at them, record it in `DECISIONS.md` and drop them from the evidence slide.

### Tests (done when)

- Contracts frozen by Friday 22:00; `make sim && make all` runs end to end with stubs by Saturday 02:00
- CI fails a merge that breaks a schema, a Tach boundary, ruff or the type checker
- `Split` leakage test: a future-stamped training row makes `fit` raise
- Schema test: a row with `count > 0` and `exposure = 0` is rejected

**Must not:** implement any module's logic; tune any module's thresholds.

**Stretch (may):** inject fake boats into real image chips across a range of wind speeds, to fit P3's detection-probability model.

## P2 Ingest

**Purpose:** get every real input onto disk, cropped to the region, cached and reproducible, so the rest of the pipeline never touches the network.

**Context:** data is the biggest risk of the weekend. Downloading radar history can stall for hours (older originals are delayed on Copernicus Data Space; full scenes are about 1 GB). This part is the only one with network access and secrets.

**Inputs:** config (region polygon, date windows, API tokens from environment variables).

**Outputs:** `raw/` files and `raw/manifest.json` exactly as in the Data dictionary.

### Steps

1. **Friday probe (go/no-go by midnight):** download one Sentinel-1 crop for the region and run one GFW query. If either fails, tell P1 immediately; everyone continues on the simulator
2. **Region:** the south and south-west coast, shore to 25 km offshore (bales have been dropped up to 20 km out), about 150 km of coast
3. **Two windows:** 24 months for ship and AIS-derived data; the latest 90 days of radar for small boats, calm passes only (use ERA5 first to pick calm passes, then download only those)
4. **Sentinel-1:** IW GRD high resolution, VV and VH, calibrated to sigma0 and terrain-corrected **server-side** (openEO on Copernicus Data Space, or the Sentinel Hub Process API), cropped to the band, saved as int16 dB × 100. Save metadata: orbit direction, relative orbit, start time, footprint, incidence range, and from the annotation XML the PRF, slant range and satellite speed (needed by P4's ghost rule)
5. **GFW** with the official Python client `gfw-api-python-client` (4Wings API): `public-global-sar-presence:latest` (SAR detections, industrial vessels, from 2017 to about 5 days ago, matched and unmatched), and `public-global-presence:latest` (AIS presence with speed bins). Loitering events are not used (they start 20 nautical miles from shore)
6. **AIS** for slowdowns: GFW public-global-presence:latest filtered to cargo and tanker vessel types and speed below 2 knots, at the finest spatial and daily temporal resolution available. GFW loitering events cannot be used (they start 20 nautical miles from shore) and the Marine Institute dataset is 2017 density rasters only (see Research on open questions)
7. **ERA5 hourly** from the Climate Data Store: `10m_u_component_of_wind`, `10m_v_component_of_wind`, `significant_height_of_combined_wind_waves_and_swell`
8. **OpenStreetMap** via Overpass: `man_made=pier`, `leisure=slipway`, `harbour=*`, plus `highway=*` within 200 m (road access); OSM coastline polygons
9. **Inshore layers:** BIM and Marine Institute under-12 m fishing activity (net, pot, dredge) from data.gov.ie; **INFOMAR** bathymetry (CC BY 4.0, keep its attribution line)
10. **Cache:** every request is a JSON dict; its SHA-256 is the file name; `manifest.json` records request, hash, UTC time and licence. `make fetch` is the only network command

### Download budget (my arithmetic)

A 150 × 25 km band at 10 m is 15,000 × 2,500 pixels; two int16 bands is about 150 MB per pass; about 25 calm passes plus 5 rough ones in 90 days is about 4.5 **GB**. Every pass for 24 months would be over 100 GB.

### Resolved ambiguities

- **Which passes to download:** a pass is downloaded if at least 50% of the region cells it covers are calm (from ERA5 at the pass hour, using P3's thresholds). Also download 5 rough passes so P1's recall curve has a rough bin, and save the footprint and time of every pass in the window, downloaded or not, with a downloaded flag in the manifest
- **Extra metadata field:** P4's ghost rule needs the flight direction, so also save `heading_deg` (platform heading) per scene
- **AIS fields:** keep ship id, time, position, speed over ground, course, ship type and length; missing length stays NaN, never 0
- **Ship history window and radar window** are the Global settings values, counted back from T

### Warnings

> **Warning:** the exact openEO collection and process names, and Sentinel Hub request fields, are not verified here. Check Copernicus Data Space docs on Friday; never guess a name and silently get a different product (for example uncalibrated digital numbers instead of sigma0).

> **Warning:** GFW SAR detections are industrial vessels only. They will show almost no small pick-up boats; that is expected, not a bug.

> **Warning:** GFW data is for non-commercial use. Record the licence in the manifest and raise it with the organisers before the prize stage.

> **Warning:** ERA5 and Sentinel-1 times are both UTC; a local-time conversion anywhere breaks the calm flag by an hour or more.

> **Warning:** never clean, filter or reinterpret data here. A filter added in ingest is invisible to every later test.

### Tests (done when)

- Friday 24:00: one real crop and one GFW query on disk
- Saturday 12:00: full windows cached; `make all` reruns with the network disabled
- Every file in `raw/` is listed in the manifest with a licence
- A re-run of `make fetch` with the same config downloads nothing new

**Must not:** transform data beyond format conversion; commit tokens; download outside the region.

**Stretch (may):** a script that refreshes the last 7 days, to show it could run weekly.

## P3 Reference and coverage

**Purpose:** the static map of what is normal at sea, and exactly which cells each satellite pass saw and how well.

**Context:** every "unusual" judgment downstream is only as good as this part's definition of normal (inshore grounds, lanes, legitimate stopping places) and its record of where we actually looked (Design principles 4, 5 and 9). It also gives the sea-only travel times that link offshore spots to piers.

**Inputs:** `raw/` static layers, scene metadata and footprints, ERA5; radar scenes only for the static-object mask.

**Outputs:** `reference/layers.gpkg` (cells, piers and land layers), `reference/sea_250m.tif`, `reference/land_mask_10m.tif, reference/static_mask_10m.tif, reference/travel_hours.parquet`, `coverage/exposure.parquet`.

### Steps: layers per 2 km cell (and aggregated to 10 km)

| Layer | How it is built | Default |
| --- | --- | --- |
| `inshore_frac` | Area of the cell inside any inshore fishing polygon ÷ cell area (`geopandas.overlay`) | — |
| `lane` | GFW AIS presence hours per cell (non-fishing vessels only if GFW allows filtering by type; otherwise all); lane if above the 90th percentile of non-empty cells | 90th percentile |
| `anchorage` | Share of the cell's presence hours in the slowest speed bin > 0.5, and total hours in the top 25% | 0.5, top 25% |
| `port_zone` | Buffer around port and harbour points | 5 km |
| `exclusion` | `port_zone` ∪ `anchorage`, grown by one cell. P4 drops slowdowns here | 1 cell |
| `static_frac` | From raw radar, not from P4's detections (P4 needs this mask before it can detect): a 50 m bin is a fixed object if its brightest VV pixel is at least 10 dB above the median of the surrounding 41 × 41 pixels in ≥ 60% of the passes that covered it; grown by 100 m; written as a 10 m raster and summarised per cell as the share it covers | 60%, 10 dB, 100 m |
| `dist_coast_m` | Distance from the cell centre to the coastline | — |
| land mask (raster) | OSM land at 10 m, plus a 300 m coastal buffer where P4 does not detect | 300 m |

### Steps: piers and sea travel times

1. Piers from OSM (`man_made=pier`, `leisure=slipway`, `harbour=*`); `road_access = True` if a road is within 200 m. Keep the OSM name; never invent one
2. Rasterise sea at 250 m: cost 1 on sea, infinite on land → `sea_250m.tif`
3. For each pier with road access: `skimage.graph.MCP_Geometric(costs).find_costs(starts=[pier_pixel])`, with pier\_pixel = the nearest sea pixel to the pier (MCP ignores infinite-cost cells, so a pier on a land pixel would silently start nowhere), gives the shortest sea-only distance to every pixel, around headlands
4. Hours = distance ÷ boat speed (default 15 knots ≈ 7.7 m/s); store a cell × pier table `travel_hours.parquet`

### Steps: coverage and the calm flag

1. For each pass: covered fraction per cell = area(footprint ∩ cell ∩ sea) ÷ full cell area, in UTM
2. For each cell and pass, ERA5 at the nearest hour and grid point: wind = √(u² + v²); `calm` if wind < 6 m/s **and** wave height < 1.5 m (defaults to tune against P1's recall curve)
3. `exposure_small` = covered fraction × calm. Rough passes become exposure 0 for small boats (Design principle 5)
4. Slowdown exposure is the cell's sea\_frac per day (AIS is continuous); reduce it only where AIS reception is known to be poor

### Parameters (config)

`lane_pct = 90`; `anchorage_share = 0.5`; `port_buffer_m = 5000`; `static_share = 0.6`; static\_db = 10; `coast_buffer_m = 300`; `sea_raster_m = 250`; `boat_speed_kn = 15`; `calm_wind_ms = 6`; `calm_hs_m = 1.5`.

### Resolved ambiguities

- **Coastal cells:** keep a cell if at least 20% of it is sea; store `sea_frac`. Covered fraction = area(footprint ∩ cell ∩ sea) ÷ full cell area, so a half-land cell can reach at most 0.5 and exposure scales with sea area (rates are then per full sea cell)
- **10 km layers from 2 km ones:** `inshore_frac` = mean of children ignoring NaN (NaN if all are NaN); `lane` = share of children that are lane cells; `dist_coast_m` and `static_frac` = means
- **"Slowest speed bin"** = GFW's lowest speed bin, whatever its range; record that range in `DECISIONS.md`
- **Calm flag is per cell per pass**, not per pass: one pass can be calm near shore and rough offshore. Passes P2 did not download get exposure\_small = 0 in every cell, even where calm

### Warnings

> **Warning:** inshore maps don't cover the whole coast. A cell with no map data must get `inshore_frac = NaN` (unknown), not 0, or every unmapped stretch looks like "outside fishing grounds" and floods the context detector.

> **Warning:** the coastline raster must be closed. One missing land pixel lets the minimum-cost path cut through a headland and makes far piers look close.

> **Warning:** the static mask is built from persistent bright spots, so a real drop site visited very often could be masked as "fixed". `P4 does blank masked pixels, so the ≥ 60% rule is the safeguard: a drop site visited every few days won't reach it. Test on the simulator that the planted drop site is never masked`.

> **Warning:** the calm thresholds are guesses. Until P1's recall curve exists, report them as provisional in every output.

> **Warning:** exclusion zones that are too small turn pilot boardings and ships waiting for a berth into "suspicious slowdowns"; too large and they hide real drops near ports. Check them on the map with a human before Saturday 18:00.

### Tests (done when)

- Every sea cell in the region has a row; every `cell_id` matches `core.grid`
- On the simulator, the planted anchorage is flagged and the planted drop site is not
- A known pass's covered area matches its footprint area within 2%
- A rough simulated pass gives `exposure_small = 0` everywhere
- Travel time from a pier to a cell behind a headland is longer than the straight-line time

**Must not:** score, rank or judge anything; every layer is a measured fact or a published dataset.

**Stretch (may):** replace the calm flag with a fitted detection probability: logit p = a + b·L − c·wind − d·wave height + e·incidence angle (`statsmodels` `Logit`, fitted on P1's recall and injection data), and use it as exposure per boat-size class.

## P4 Detect and match

**Purpose:** turn radar scenes into small-boat detections with honest probabilities, and AIS into ship-slowdown events.

**Context:** small pick-up boats are the core target and appear as a bright blob of a few pixels at about 20 m resolution (Design principle 3). No single detection is certain, so each carries a probability. Large ships are handled by GFW and AIS; this part only turns their behaviour into slowdown events.

**Inputs:** `raw/s1/*` scenes and metadata, `raw/gfw_sar.parquet`, AIS source, `reference/land_mask_10m.tif`, `reference/static_mask_10m.tif`, `reference/layers.gpkg` (`exclusion`), `coverage/exposure.parquet` (to pick calm passes).

**Outputs:** `detect/detections.parquet`, `match/events.parquet`.

### Steps: CFAR detector (VV and VH separately, calm passes only)

1. Convert int16 dB × 100 to **linear** sigma0: I = 10^(value ÷ 1000). Set land, the 300 m buffer and static objects to NaN
2. Background ring per pixel: outer 41 × 41 window (410 m) minus inner 11 × 11 guard (110 m), so a boat doesn't raise its own background. With box means from a NaN-aware `uniform_filter`:

```latex
\mu_b = \frac{41^2 \cdot \bar I_{41} - 11^2 \cdot \bar I_{11}}{41^2 - 11^2}
```

3. Flag a pixel if I > α · μ\_b. Starting α = `scipy.stats.gamma.isf(P_fa, a=L, scale=1/L)`, where L, the equivalent number of looks, is estimated on open calm sea as mean² ÷ variance
4. Start with P\_fa = 10⁻⁷: over about 3.75 × 10⁷ sea pixels that is about 4 false pixels per pass per polarisation (my arithmetic). **Then calibrate α on the injection and null tests**, because real clutter has heavier tails than gamma
5. Cluster flagged pixels with `scipy.ndimage.label` (8-connectivity); keep clusters of 1–200 pixels; record centroid, pixel count, peak ratio I ÷ μ\_b in dB
6. `pol_agree` = a VV and a VH cluster within 30 m. Merge them into one candidate
7. `size_class` from pixel count: 1–4 small, 5–20 medium, > 20 large (very rough at this resolution)

### Steps: ghost rule

Azimuth ambiguities appear displaced along the flight direction by about

```latex
\Delta_{az} = \frac{\lambda \, R \, f_{PRF}}{2 \, V_s}
```

(λ ≈ 5.55 cm, R slant range, f\_PRF pulse repetition frequency, V\_s satellite speed, all from the scene's metadata). A candidate is `ghost = True` if the radar image itself (not the candidate list, which drops large bright objects and land) has a pixel at least 20 dB brighter about ±Δ away along the azimuth direction (tolerance ±200 m).

### Steps: detection probability

1. Features per candidate: peak ratio VV and VH, `pol_agree`, pixel count, wind at pass time, `ghost`
2. Training data from P1's injection runs: positives = candidates at injected boats; negatives = candidates in the same chips more than 500 m from any injection or AIS ship
3. Fit logistic regression (`statsmodels` `Logit`); `p_boat` = its prediction; ghosts are kept but get the model's (low) probability
4. Dawid–Skene only if a third independent view exists (for example a pretrained xView3 model): EM from a majority-vote start, alternating per-candidate posteriors and per-view sensitivity and specificity (`crowd-kit` `DawidSkene`)

### Steps: matching to AIS

1. For each pass, AIS positions within ±30 min of scan time; interpolate linearly in UTM to scan time; never across gaps over 30 min
2. Cost = distance; pairs over 500 m get a large finite cost (1e9, because scipy can reject infinite costs); after assignment, drop any pair over 500 m
3. One-to-one assignment: `scipy.optimize.linear_sum_assignment`
4. Unmatched `small` (and `medium`) candidates become `dark_small` events with `p = p_boat`

### Steps: ship slowdown events

1. Cargo (AIS ship types 70–79) and tankers (80–89) only
2. Speed = 10-minute rolling median of speed over ground
3. Event if the previous hour's median ≥ 8 knots, then < 3 knots for ≥ 20 minutes, outside `exclusion`, with wave height < 4 m
4. Record the slow segment's median position, start time, duration; `p = 1.0`; `ship_key` = salted SHA-256 of the ship id (salt from an environment variable)
5. `With GFW presence (the expected source): one slowdown event per cell-day with cargo or tanker presence-hours below 2 knots outside exclusion; p = 1.0; duration_min = presence-hours × 60; no ship_key. The per-ship rules above apply only if a track source turns up`

### Parameters (config)

`cfar_outer = 41`; `cfar_guard = 11`; `p_fa = 1e-7` (then calibrated); `cluster_px = [1, 200]`; `pol_agree_m = 30`; `ghost_db = 20`; `ghost_tol_m = 200`; `ais_window_min = 30`; `match_gate_m = 500`; `slow_kn = 3`; `cruise_kn = 8`; `slow_min = 20`; `storm_hs_m = 4`.

### Resolved ambiguities

- **"Calm passes only":** run CFAR on the whole downloaded pass, then drop candidates in cells where that pass's `calm` is False. Those cells have exposure 0 anyway
- **Size class after merging VV and VH:** use the larger pixel count of the two
- **`dark_small` covers small and medium candidates;** keep `size_class` so later steps can filter
- **Ghost brightness** = the cluster's peak sigma0 in dB. **Azimuth direction** = the scene's `heading_deg`, applied in UTM; search along that line on both sides
- **Logistic negatives** may include a few real dark boats; that is accepted and makes `p_boat` slightly conservative
- **Wind feature** comes from `coverage/exposure.parquet`, joined on (`cell_id`, `pass_id`)
- **Sparse AIS:** a slowdown needs at least 3 pings in the previous hour and 2 in the slow segment; otherwise skip it, never interpolate a slowdown into existence

### Warnings

> **Warning:** always run CFAR on linear power. Averaging dB values gives a biased background and wrong thresholds, with no error raised.

> **Warning:** the ghost offset formula and the metadata field names are not verified here. Before trusting the rule, check it on one real scene with a known bright ship and see that its ghost appears where predicted.

> **Warning:** a 500 m match gate may be too tight for fast ships, which radar shows displaced along the flight direction. If many large AIS ships come out "dark", widen the gate along azimuth before blaming the detector.

> **Warning:** coastal stretches with poor AIS reception make legitimate ships look dark. Only small and medium candidates become events, and P6 treats them as probabilities, but flag any area where most large ships are unmatched.

> **Warning:** ships slow down for normal reasons (pilot boarding, waiting for a berth, bad weather, engine trouble). Exclusion zones and the storm filter handle most; never call a slowdown suspicious on its own. Only the later small-boat visit makes it interesting.

> **Warning:** the raw ship id must never be written to any stage file; only `ship_key`, and never to the export.

### Tests (done when)

- Simulator: planted boats recovered at the planted detection rate within 10%; ghosts flagged at least 80% of the time
- Injection: recall and false alarms per brightness reported to P1
- No slowdown events inside `exclusion` (by construction)
- Real data: share of large GFW detections that match AIS is reported; a sudden drop signals a matching bug

**Must not:** aggregate, forecast or rank; read `sim/truth.parquet`.

**Stretch (may):** a pretrained xView3 model as a third view, enabling Dawid–Skene.

## P5 Aggregate and forecast

**Purpose:** count events per cell and day with their exposure, and predict what normal looks like for each event type.

**Context:** this is "forecast normal" (Design principle 2). The expected count μ is the yardstick for every surprise in P6, so a biased μ makes everything downstream wrong. Most cells are near zero most days, so stabilising sparse cells matters as much as the model.

**Inputs:** `match/events.parquet`, `coverage/exposure.parquet`, `reference/layers.gpkg`; a `core.Split` for every fit.

**Outputs:** `aggregate/observed.parquet`, `forecast/expected.parquet`.

### Steps: aggregate

1. Assign each event to its 2 km cell and UTC date
2. Soft count C = sum of `p` per cell, date and event type
3. Exposure E: for `dark_small`, sum of `exposure_small` over that day's passes; for `slowdown`, the cell's sea\_frac per day
4. Write every (cell, date, type) row, including E = 0 rows with C = 0 (marked unobserved), so the time series has no gaps
5. Also aggregate to 10 km by summing C and E over the 25 child cells

### Steps: baseline 1, exposure-aware EWMA (build first)

Per cell and type, two decayed sums updated daily in date order:

```latex
S_C \leftarrow \delta S_C + C_d \qquad S_E \leftarrow \delta S_E + E_d \qquad \hat r = S_C / S_E \qquad \mu = \hat r \cdot E
```

with δ = 0.97 per day (half-life about 23 days). Unobserved days add 0 to both sums, so they can't drag the rate down. Start both sums at 0. Until a cell's S\_E reaches 3, use its 10 km parent's EWMA rate (computed the same way) times the fine cell's E. Do not divide by 25: the parent rate comes from summed counts over summed exposures, so it is already a per-cell rate. μ for day d uses the sums as they stood after day d − 1; day d's own count is added only after day d has been scored.

### Steps: baseline 2, quasi-Poisson regression with empirical Bayes (the upgrade)

1. Fit on the 10 km grid, one model per event type, training rows with E > 0 only:

```latex
\log \mu = \log E + \beta_0 + \beta_1 \, \text{inshore} + \beta_2 \, \text{lane} + \beta_3 \log(\text{dist\_coast}) + \beta_4 \sin\tfrac{2\pi d}{365} + \beta_5 \cos\tfrac{2\pi d}{365}
```

Code: `sm.GLM(C, X, family=sm.families.Poisson(), offset=np.log(E)).fit(scale="X2")`. The fitted scale is the dispersion φ; soft (non-integer) counts are allowed. Where `inshore_frac` is unknown (NaN), add a missing-indicator column and set the value to 0

2. Empirical Bayes per 10 km cell, with O = observed total and M = model expected total over the training window:

```latex
\tilde\theta_c = \frac{a + O_c}{a + M_c} \qquad a = \frac{\sum_c M_c^2}{\sum_c \left[(O_c - M_c)^2 - M_c\right]}
```

If the denominator of a is ≤ 0, set θ̃ = 1 for all cells (no extra variation)

3. Fine-cell expected count: μ = E × exp(xβ with the fine cell's covariates) × θ̃ of its 10 km parent

### Steps: intervals and backtest

- 90% interval per row from a negative binomial with mean μ and variance φμ: size k = μ ÷ (φ − 1) if φ > 1, else Poisson (`scipy.stats.nbinom`, `scipy.stats.poisson`)
- Walk-forward over the last 12 weeks for slowdowns and the last 6 weeks for dark\_small: for each fold, fit on `split.train()` only, predict `split.test()`, score mean Poisson deviance. Skill = 1 − D\_model ÷ D\_flat, where "flat" is each cell's training-average rate × E
- Keep the baseline (EWMA or regression) with the higher mean skill; record the choice in `DECISIONS.md`

### Parameters (config)

`ewma_delta = 0.97`; `coarse_m = 10000`; `n_folds_slowdown = 12; n_folds_small = 6`; `embargo_days = 7`; `interval = 0.9`.

### Resolved ambiguities

- **Training rows:** everything from the start of that event type's history up to the fold cutoff (24 months for slowdowns, up to 90 days for `dark_small`). The production forecast for the evaluation window (fold = 0 in expected.parquet) is fitted only on rows before the evaluation window starts, so the days being scored never shape their own baseline; backtest rows carry their fold number
- **10 km covariates** come from P3's aggregation rules; fine cells use their own covariates with the coarse fit's coefficients
- **Choosing a baseline** is done separately per event type; the two types may end up with different models
- **Partly-land cells:** exposure already scales with the cell's sea area (P3), so rates are per full sea cell and need no further correction

### Warnings

> **Warning:** never fit on rows with E = 0. Their C = 0 is "not looked", and including them teaches the model the sea is emptier than it is.

> **Warning:** forgetting the offset log E makes cells that were imaged more often look busier, which then shows up as "unusual".

> **Warning:** any rolling or seasonal feature computed over the whole series before splitting leaks the future. Compute features inside each fold from training rows only.

> **Warning:** Sentinel-1B stopped in December 2021 and Sentinel-1C started in 2025; pass frequency changes over the window. Exposure handles this only if E is computed from actual passes, never assumed.

> **Warning:** with only 90 days of small-boat radar, the seasonal terms for `dark_small` can't be estimated. Drop the sine and cosine terms for that type and say so.

### Tests (done when)

- Simulator: planted normal rates recovered within 20%; planted drop-site days are not absorbed into the baseline (their μ stays below the observed count)
- Leakage test passes (a future row makes `fit` raise)
- Backtest skill > 0 for the chosen baseline, reported with its range over folds
- No row in `expected.parquet` has μ < 0 or a missing interval where E > 0

**Must not:** score surprise, rank, or read detector outputs.

**Stretch (may):** recall-corrected estimates of true dark counts (C divided by the recall for that size class and sea state, with intervals), shown as "estimated boats".

## P6 Detectors and fuse

**Purpose:** decide what is surprising in each cell, then link ship slowdowns to later small-boat visits and to the piers they could reach.

**Context:** this is where "find the drop, not the boat" becomes numbers (Design principles 1 and 8). Four cheap detectors look at the same counts from different angles; their agreement gives both a score and plain-language reasons. The lag link encodes how drop-offs actually work: a large ship pauses, and a small boat visits the same spot hours to days later.

**Inputs:** `aggregate/observed.parquet`, `forecast/expected.parquet`, `reference/layers.gpkg`, `reference/travel_hours.parquet`, `match/events.parquet` (slowdown positions only).

**Outputs:** `fuse/cells.parquet` (per-cell scores, for heat maps), `fuse/sites.parquet`.

### Steps: the four detectors (observed rows only, E > 0)

**1. Tail surprise (one cell, one day).** With c = round(C) and X negative binomial with mean μ and variance φμ (Poisson if φ ≤ 1):

```latex
p_{mid} = P(X > c) + \tfrac{1}{2} P(X = c)
```

Then Benjamini–Hochberg at q = 0.1 over **all** (cell, day, type) rows in the evaluation window at once: `multipletests(p_mid, alpha=0.1, method="fdr_bh")` → `bh_flag`.

**2. Gi\* hotspots (neighbourhood, weekly).** Weekly sums of C and μ per cell; y = (C + 0.5) ÷ (μ + 0.5). Weights: `libpysal.weights.DistanceBand` with threshold 2,900 m on cell centroids, built over observed cells only. Run `esda.G_Local(y, w, star=True, permutations=999)`; keep the z-score as `gi_z`.

**3. CUSUM (build-up over days).** Per cell, on observed days in date order, with z = (C − μ) ÷ √(max(φ, 1) · μ):

```latex
S_d = \max(0,\; S_{d-1} + z_d - k), \qquad \text{alarm if } S_d > h, \quad k = 0.5,\; h = 4
```

Unobserved days leave S unchanged; S resets to 0 after an alarm.

**4. Context rule.** Mean of yes/no facts; unknown facts (NaN inputs) are left out of the mean, not counted as yes or no:

- `dark_small`: outside inshore grounds (`inshore_frac` < 0.1); 2–25 km from the coast; first calm pass within 72 h after ≥ 24 h of waves over 2.5 m
- `slowdown`: outside lane cells; stop lasted 20–180 minutes

**Fusion.** Within each event type, convert each detector's output to a percentile rank over all observed (cell, day) rows in the evaluation window (ranking per day is unstable when only a few cells were seen) (`rank(pct=True)`; for `p_mid`, rank 1 − p). U = mean of the four ranks. `agreement` = number of detectors placing the cell in their own top 10%.

### Steps: lag link

For each slowdown s at cell c\_s and time t\_s:

1. Neighbourhood N = cells with centroids within 4 km of c\_s; window = (t\_s, t\_s + 7 days\]
2. Follow-up exposure X = sum of `dark_small` exposure over N × window. **If X = 0, count the slowdown as "follow-up unobserved" and give it no link score**
3. Otherwise, with τ = 3 days:

```latex
L_s = U_{slowdown}(s) \cdot \max_{c \in N,\; t \in \text{window},\; E>0} \left[ U_{small}(c,t) \cdot e^{-(t - t_s)/\tau} \right]
```

### Steps: sites, significance, recurrence, piers

1. **Sites:** cluster slowdown positions (metres) with `DBSCAN(eps=3000, min_samples=1)`
2. **Site score:** S = Σ L\_s × 2^(−age ÷ 30 days), age measured from the end of the evaluation window
3. **Permutation test:** shift all slowdown times by one random offset of up to ±60 days, wrapping circularly within \[radar start, T\], recompute S for every site; 999 shuffles. p\_perm = (1 + shuffles ≥ observed) ÷ 1,000. Benjamini–Hochberg at q = 0.1 across sites → `bh_flag`
4. **Recurrence:** distinct slowdowns in the site with L\_s above the median of all L
5. **Pier score:** P\_j = Σ over flagged sites of S × exp(−T ÷ 1 hour), T from `travel_hours`, road-access piers only; top 3 piers per site
6. **Reasons:** fill a template from the numbers, for example "Cargo ship slowed for 42 min, 14 km offshore, outside lanes. 2 days later: 1.8 small unmatched detections where 0.1 were expected. Outside inshore grounds. First calm pass after a storm." Never include a vessel identity

### Parameters (config)

`fdr_q = 0.1`; `gi_band_m = 2900`; `gi_perm = 999`; `cusum_k = 0.5`; `cusum_h = 4`; `top_frac = 0.1`; `link_radius_m = 4000`; `link_days = 7`; `tau_days = 3`; `dbscan_eps_m = 3000`; `half_life_days = 30`; `shift_days = 60`; `n_shuffles = 999`; `pier_tau_h = 1`.

### Resolved ambiguities

- **U\_slowdown(s)** = U of the slowdown type for s's cell on s's UTC date. **U\_small(c, t)** = U of the `dark_small` type for cell c on day t
- **Gi\* is weekly but U is daily:** give each observed day the `gi_z` of its week
- **CUSUM in the ranking** uses the value `cusum_s`, not the yes/no alarm. Mid-p values are slightly less conservative than exact p-values; the null test checks the resulting flag rate
- **Which slowdowns get linked:** those whose 7-day follow-up window overlaps the radar history; older ones have no L, so they count only toward the site's n\_slowdowns, not its score or recurrence
- **Permutation:** keep each slowdown's cell and U; shift only its time, wrapping within \[radar start, T\]; recompute follow-up exposure and L. Shifted slowdowns that land on unobserved windows are treated exactly like real ones
- Site agreement = the agreement of the dark\_small cell-day that gave the highest L in the site. **No flagged sites:** compute pier scores from the top 5 unflagged sites and label everything "not significant"

### Warnings

> **Warning:** Benjamini–Hochberg must run once over the whole set of tests. Running it per day or per cell makes far more flags than q promises.

> **Warning:** percentile ranks must be computed over the same set of observed cells for all four detectors. Ranking each over a different set makes U meaningless.

> **Warning:** the four detectors use the same counts, so 4/4 agreement is not four independent proofs. Show it as "angles that agree", never as a probability.

> **Warning:** a slowdown with no observed follow-up must never get L = 0. Zero says "we looked and nothing came"; the truth is "we couldn't look". Mixing them hides exactly the drops that happen in rough weather.

> **Warning:** busy areas produce chance links (many slowdowns, many small boats). The permutation test exists to remove them; never skip it to save time. Fix the seed so results are reproducible.

> **Warning:** choose the lag window (7 days), radius (4 km) and τ before looking at real data, and never retune them after seeing which sites come out on top.

### Tests (done when)

- Simulator: the planted drop site is the top site with `bh_flag`; a planted slowdown with no planted visit is not flagged
- Null test (from P1): share of runs with any flagged site ≤ about q
- Every flagged site has non-empty reasons and at least one pier (or says "no road-access pier within reach")
- `followup_unobserved` is counted and shown, never silently dropped

**Must not:** read `raw/`, re-detect, re-forecast, or output identities.

**Stretch (may):** a calibrated probability per site, fitted on simulator runs and checked with P1's calibration plot.

## P7 Patrol, export, dashboard, pitch

**Purpose:** turn ranked sites into a plan the Naval Service and Air Corps could act on, freeze everything into one snapshot, and show it.

**Context:** with 2–3 ships for 437,500 km², the output must be a short list and a route, not a map of everything (Design principle 13). One exploration visit keeps the system from only confirming itself. The demo must work without internet at the venue, and must never name a vessel or person (principle 10).

**Inputs:** `fuse/sites.parquet`, `fuse/cells.parquet`, `forecast/expected.parquet`, `coverage/exposure.parquet`, `reference/layers.gpkg`, `reference/sea_250m.tif`, `reports/validation.json` (from P1).

**Outputs:** `patrol/plan.json`, `export/snapshot.json`, `dashboard/index.html`, pitch deck, demo video.

### Steps: ship plan (orienteering with a time budget)

1. Nodes: the base port plus the top 15 sites with `bh_flag`
2. Travel hours between all nodes from `sea_250m.tif` with `skimage.graph.MCP_Geometric`, at 12 knots; 1 hour on station per site
3. Greedy insertion: repeatedly add the site with the highest S ÷ extra hours, at the cheapest position in the route, while the total stays within 24 hours (out and back)
4. 2-opt: reverse any route segment that shortens total time; repeat until no gain
5. Exploration slot: reserve one visit among sites ranked 4–15. For each, resample its slowdowns 200 times to get a distribution of S; draw once from each; pick the highest draw. Seed = global seed + ISO week number

### Steps: aircraft plan

The same planner with straight-line distances, aircraft speed and dwell from config (defaults: 4 flight hours, 0.2 h per site), no exploration slot. Its role is to sweep many sites fast so ships follow up on what it sees.

### Steps: export (`snapshot.json`)

| Key | Contents |
| --- | --- |
| `meta` | `data_label` ("simulated", "real" or "mixed", set by the pipeline from the stage files' provenance, never by hand), generation time, region, week, config hash |
| `basemap` | Coastline as GeoJSON, simplified with `shapely` `simplify(50)` in metres, then converted to WGS 84 |
| `cells` | Per cell and week: the four heat-map values (see Maps and heat maps) and an `observed` flag |
| `sites` | id, position, S, p\_perm, `bh_flag`, recurrence, agreement, `followup_unobserved`, reasons, top 3 piers |
| `piers` | id, OSM name, position, P\_j |
| `plan` | ordered stops with arrival times, for the ship and the aircraft |
| `validation` | recall table, forecast skill with range, calibration bins and Brier score, null-test share of runs with any flag, provisional-threshold notes |

A test scans the snapshot and fails the build on anything resembling an MMSI (9-digit number), IMO number or call sign.

### Steps: dashboard

1. One `index.html`, plain JavaScript and inline SVG, written during the weekend. The prototype from before the event is a design reference only
2. Projection: the snapshot's WGS 84 coordinates drawn with a simple equirectangular scaling for the region (accurate enough for 150 km); no tile server, no internet
3. Layout: map (one heat map selector + overlays, see Maps and heat maps); ranked site list with reasons, agreement badge and p-value; plan panel with both routes and timings; validation panel; banner with `data_label`; week selector
4. Unobserved cells hatched grey; legends with units

### Steps: pitch (3 minutes; the Judging scorecard's pitch plan replaces this list)

1. The problem: 2–3 ships for 437,500 km²; drop-offs are the main route for cocaine into Europe
2. The idea: find the drop, not the boat
3. Live demo: one site, its reasons, its piers, the plan
4. The proof: recall by boat size, forecast skill, null test, and the five traps we designed out
5. The limits: pick-ups between passes, small boats in rough seas, places not people
6. Galileo: one slide on using Galileo's authenticated signal (OSNMA) to give patrol evidence a trustworthy position and time, if the organisers confirm it fits (unverified idea)

Record a 90-second screen capture by Sunday 10:00 as the fallback.

### Parameters (config)

`top_sites = 15`; `ship_kn = 12`; `ship_budget_h = 24`; `ship_dwell_h = 1`; `n_boot = 200`; `aircraft_budget_h = 4`; `aircraft_dwell_h = 0.2`; aircraft\_kn = 180 (TODO: confirm with the team).

### Resolved ambiguities

- **Base port** = Haulbowline, Cork Harbour (Global settings)
- **Fewer than 15 flagged sites:** fill the candidate list with unflagged sites by S, each labelled "not significant" in the plan and dashboard
- **Fewer than 4 sites in total:** skip the exploration slot
- **Bootstrap for exploration:** resample the site's L values with replacement 200 times and recompute S each time
- **Weeks shown:** the week containing T and the 3 before (Global settings)

### Warnings

> **Warning:** straight-line distances for ships cut across headlands and make routes impossible. Ships always use sea distances.

> **Warning:** `data_label` must come from the data, never from a hard-coded string. A demo of simulated data labelled "real" is the fastest way to lose the judges' trust.

> **Warning:** the browser computes nothing beyond sorting and formatting. A score computed in JavaScript is untested and can disagree with the pipeline.

> **Warning:** never load map tiles from the internet; venue Wi-Fi may fail during the pitch.

> **Warning:** the exploration draw must be seeded; an unseeded draw changes the plan every time the page is regenerated during the demo.

### Tests (done when)

- Dashboard renders the simulator snapshot by Saturday 12:00 and the real one by Saturday 22:00
- Plan total time ≤ budget; every stop is reachable by sea
- Identity scan of the snapshot passes
- Demo video recorded by Sunday 10:00

**Must not:** compute scores; add data not in the snapshot; show identities.

**Stretch (may):** a replay control stepping week by week through past snapshots.

## Pseudo-codebase (practice pass, 27 November)

Every public function each module needs, with its signature, what it reads and writes, the steps, and the test that proves it. Agents implement these names exactly; private helpers are free. This is a design spec written in plain-language pseudocode, not code: all real code is still written during the weekend (fresh-code rule), and nothing here is to be pasted in.

Conventions: `fn name(arg: type) -> type`; positions in metres (EPSG:32629), times UTC; "→ file" means the function writes that stage file through core.io. Every function that fits anything takes a core.Split.

### Issues found during the practice pass

Writing each function against the specs turned up nine gaps. The resolutions below are adopted; where they differ from a module spec above, this table wins.

| # | Issue | Resolution | Affects |
| --- | --- | --- | --- |
| 1 | There are no historical AIS positions (GFW presence is gridded hours), so radar detections can't be matched to AIS ship by ship | Match to GFW SAR detections from the same pass: a candidate within 500 m of a GFW detection with matched = True is matched. If GFW only returns gridded SAR presence, skip matching, mark every small and medium candidate unmatched, and say so in the pitch. Most AIS carriers are over 15 m and fall in the large class anyway | P2, P4 |
| 2 | P1's real-data recall curve needs AIS positions of small boats, which we don't have | Small-boat recall comes from the simulator and injection tests only; on real data, report recall only for GFW-matched vessels (mostly 15 m and over) | P1 |
| 3 | Slowdowns from GFW presence are cell-days with no time of day, no per-ship duration and no cruise-speed check | Slowdown time = 12:00 UTC of its date; the lag window is \[date, date + 7 days\] so a same-day pick-up still counts; the context rule "stop lasted 20–180 min" becomes "slow presence-hours between 0.33 and 3"; the "previous hour ≥ 8 knots" check is dropped | P4, P6 |
| 4 | GFW's grid is not our 2 km grid | New P3 function regrid\_presence (area-weighted); raw/gfw\_presence.parquet must keep a vessel\_type column | P2, P3 |
| 5 | The land and static masks are on "the same 10 m grid as the radar crops", but nothing fixes that grid | P2 resamples every scene onto one fixed region grid: EPSG:32629, 10 m, origin (x0, y0) from config (openEO resample\_spatial) | P2, P3, P4 |
| 6 | openEO does not return annotation metadata (PRF, slant range, heading) | Ghost search uses the 4–8 km band; heading approximated from orbit direction; checked on one real bright ship | P2, P4 |
| 7 | inshore\_frac = NaN ("no map") needs to know where the map was surveyed, not just where fishing is | P2 saves the dataset's survey extent polygon; if none is published, open a question issue | P2, P3 |
| 8 | P4 reads raster scenes, but the simulator spec only described tables | The simulator renders small raster chips with gamma speckle (L = 4.4) | P1 |
| 9 | The P2 spec still said to check loitering events | Removed | P2 |

### P1: core/, sim/, validate/

```text
core/crs
  fn to_utm(lon, lat: array) -> (x_m, y_m)        pyproj Transformer(4326, 32629, always_xy=True)
  fn to_wgs84(x_m, y_m: array) -> (lon, lat)       inverse transformer, for export only
  test: Haulbowline round-trips within 1 m

core/grid
  fn cell_index(x_m, y_m, s: 2000 | 10000) -> (ix, iy)   floor((x - x0) / s), floor((y - y0) / s)
  fn cell_id(ix, iy, s) -> str                           "{s}_{ix}_{iy}"
  fn parent(cell_id) -> cell_id                          (ix // 5, iy // 5) at s = 10000
  fn centroid(cell_id) -> (x_m, y_m)
  fn neighbours(cell_ids, radius_m) -> dict[cell_id, list[cell_id]]   centroid distance <= radius
  test: the 25 children of one 10 km cell all return it as parent

core/time
  fn utc(ts) -> Timestamp          raise on naive timestamps
  fn utc_date(ts) -> date
  fn iso_week(d: date) -> (year, week)

core/config
  fn load(path = "config.yaml") -> (Config, sha256)    Config is frozen
  fn snapshot_date(manifest) -> T                      min of the latest radar, GFW presence, GFW SAR and ERA5 dates (A11)

core/observed
  class Observed(frame[cell_id, level, date, event_type, count, exposure])
    on build: raise if exposure < 0, or count > 0 where exposure = 0
    fn observed_rows() -> frame       rows with exposure > 0
    fn rate() -> series               count / exposure, observed rows only

core/split
  class Split(cutoff: date, embargo_days = 7, test_days = 7)
    fn train(frame) -> frame          rows with date < cutoff
    fn test(frame) -> frame           cutoff + embargo <= date < cutoff + embargo + test_days
    fn assert_train(frame)            raise if any date >= cutoff
  fn folds(T, k_max) -> list[Split]   fold k tests [T - 7k + 1, T - 7k + 7]

core/schemas
  one pandera schema per stage file (Data dictionary); fn check(name, frame) -> frame

core/io
  fn stage_path(name) -> Path                          data/<stage>/<file>
  fn read_stage(name) -> frame                         check schema; raise if the hash of the config keys this stage reads differs (A10)
  fn write_stage(name, frame, provenance: "simulated" | "real")   check schema; stamp config hash and seed
  test: writing count > 0 with exposure 0 raises

sim/simulate
  fn simulate(config, seed) -> None
    1. make_map(seed): coastline, 6 piers (4 with road access), inshore polygons within 5 km, 1 lane, 1 anchorage, 1 wind farm
    2. make_weather(days = 120, seed): daily wind (m/s) and wave height (m), with storms
    3. make_true_boats: Poisson per cell-day; log rate = beta0 + beta1 * inshore + beta2 * lane (+ gamma term)
    4. make_slowdowns: high rate in anchorage and port zones; planted site every ~10 days
    5. make_pickups: probability 0.8, delay uniform 0.2-4 days; 70% of rough-day pick-ups moved to the next calm day
    6. make_passes: every 1-3 days, partial footprints
    7. observe: detect with p = sigmoid(a + b * L - c * wind); false alarms 0.002 per km2 per pass; ghosts at the offset
    8. render_scene(boats, clutter, L = 4.4) -> raster chips shaped like raw/s1   (issue 8)
    9. write raw/-shaped files and every stage file with its own code (never import P2-P7)
   10. write sim/truth.parquet (only validate reads it)
  test: same seed gives identical file hashes; p_det(10 m, 3 m/s) ~ 0.18

validate/
  fn wilson(k, n, z = 1.96) -> (lo, hi)
  fn recall_curve(detections, truth) -> table           simulator truth; real data: GFW-matched vessels only (issue 2)
  fn injection_test(pass_ids, brightness_db, n_per_pass, seed) -> table
       add a Gaussian spot (sigma 1 px) in LINEAR power, call detect.run_pass, recovered if within 30 m; false alarms per km2
  fn simulator_recovery() -> dict                       planted site rank; planted rates within 20%
  fn null_test(runs = 200, seed) -> share_with_any_flag  circular time shift per cell, then fuse.run; fewer runs if one fuse.run takes > 30 s, with a Wilson interval (A13)
  fn backtest(event_type) -> table                      calls forecast.backtest; mean, min, max skill
  fn calibration(pred, outcome, bins = 10, min_n = 20) -> (table, brier)
  fn interval_coverage(expected, observed) -> share of observed rows inside the 90% interval   target about 0.9 (A14)
  fn write_report(results) -> reports/validation.json   keys as in P1 resolved ambiguities
```

### P2: ingest/

```text
ingest/cache
  fn request_key(request: dict) -> str         SHA-256 of canonical JSON (sorted keys)
  fn cached(request) -> Path | None
  fn record(request, path, licence) -> None    append to raw/manifest.json with UTC time

ingest/probe
  fn probe() -> (s1_ok, gfw_ok, notes)         Friday go/no-go: one crop, one GFW presence query

ingest/s1
  fn list_passes(bbox, start, end) -> table[pass_id, time, orbit_dir, rel_orbit, footprint]
  fn select_passes(passes, era5) -> table + downloaded flag    >= 50% of covered cells calm, plus 5 rough
  fn fetch_scene(pass) -> raw/s1/<hash>.tif + .json
       openEO: load_collection("SENTINEL1_GRD", bbox, time, bands VV, VH)
               -> sar_backscatter(coefficient = "sigma0-ellipsoid")
               -> resample_spatial(EPSG:32629, 10 m, fixed origin)   (issue 5)
               -> batch job -> GeoTIFF -> int16 dB x 100
       metadata: id, time, orbit dir, rel orbit, footprint, incidence min/max; PRF, slant range, heading = null if absent (issue 6)

ingest/gfw   (gfw-api-python-client, token from env GFW_TOKEN)
  fn fetch_sar(bbox, start, end) -> raw/gfw_sar.parquet          keep per-detection rows if offered (issue 1)
  fn fetch_presence(bbox, start, end) -> raw/gfw_presence.parquet  daily, finest grid, columns incl. vessel_type and speed bin (issue 4)

ingest/era5
  fn fetch_era5(bbox, start, end) -> raw/era5.nc                 cdsapi; the three variables in P2

ingest/osm
  fn fetch_piers(bbox) -> raw/osm_piers.geojson                  Overpass: pier, slipway, harbour, roads within 200 m
  fn fetch_coastline(bbox) -> raw/coastline.gpkg

ingest/static
  fn fetch_inshore() -> raw/inshore/*.gpkg + survey extent polygon (issue 7)
  fn fetch_bathy() -> raw/infomar_bathy.tif

ingest/run
  fn fetch_all(config) -> None        make fetch; idempotent
  test: a second fetch_all downloads nothing; every raw file is in the manifest with a licence
```

### P3: reference/, coverage/

```text
reference/cells
  fn build_cells(region, coastline) -> cells[cell_id, level, geometry, sea_frac]   keep sea_frac >= 0.2
  fn inshore_frac(cells, inshore, extent) -> series      NaN outside the survey extent, not 0
  fn regrid_presence(presence) -> frame[cell_id, date, vessel_type, speed_bin, hours]   area-weighted (issue 4)
  fn lanes(cells, presence2km) -> bool                   non-fishing hours > 90th percentile of non-empty cells
  fn anchorages(cells, presence2km) -> bool              slowest-bin share > 0.5 and hours in top 25%
  fn port_zones(cells, harbours, buffer_m = 5000) -> bool
  fn exclusion(port_zone, anchorage) -> bool             union, grown by one cell
  fn dist_coast(cells, coastline) -> float
  fn to_coarse(cells2km) -> cells10km                    rules in P3 resolved ambiguities

reference/masks
  fn land_mask_10m(coastline, buffer_m = 300) -> uint8 raster on the fixed grid
  fn static_mask_10m(scenes, land_mask) -> uint8 raster   50 m bins, >= 10 dB over 41x41 median in >= 60% of covering passes, grow 100 m
  fn static_frac(cells, static_mask) -> float
  test: the simulator's planted drop site is never masked

reference/piers
  fn piers(osm, roads) -> frame[pier_id, name, geometry, road_access]
  fn sea_raster(coastline, res_m = 250) -> uint8; fn assert_closed(sea)   flood-fill check for leaks

reference/land
  fn land(coastline, region) -> frame[id, geometry]   coastline lines closed into land polygons (land on the left, OSM); #133
  fn travel_hours(sea, piers, kn = 15) -> frame[cell_id, pier_id, hours]  MCP_Geometric from the nearest sea pixel

coverage/
  fn covered_frac(footprint, cells) -> series        area(footprint & cell & sea) / full cell area
  fn weather_at(era5, cells, time) -> (wind_ms, hs_m) nearest hour; nearest grid point, and for hs the nearest point with valid waves (A8); wind = sqrt(u2 + v2)
  fn calm(wind_ms, hs_m) -> bool                      wind < 6 and hs < 1.5
  fn build_exposure(passes, cells, era5) -> coverage/exposure.parquet   not downloaded -> exposure_small 0; adds post_storm bool: >= 24 h of hs > 2.5 m in the 72 h before the pass (A9)
```

### P4: detect/, match/

```text
detect/scene
  fn load_scene(pass_id) -> (vv, vh, meta)      linear sigma0: I = 10 ** (value / 1000)
  fn apply_masks(img, land, static) -> img      masked pixels set to NaN

detect/cfar
  fn estimate_enl(img, patch) -> L              mean2 / variance on open calm sea; default 4.4
  fn background(img, outer = 41, guard = 11) -> mu_b   NaN-aware box sums: (outer - guard) / (n_outer - n_guard)
  fn alpha(L, p_fa = 1e-7) -> float             gamma.isf(p_fa, a = L, scale = 1 / L)
  fn flag(img, mu_b, alpha) -> bool mask
  fn clusters(mask, img, mu_b) -> table[x_m, y_m, n_px, peak_ratio_db]   ndimage.label, 8-connected, 1-200 px
  fn merge_pols(vv, vh, gate_m = 30) -> candidates[pol_agree, n_px = max of both, peaks]
  fn size_class(n_px) -> "small" | "medium" | "large"   1-4, 5-20, > 20

detect/ghost
  fn ghost_offset_m(meta) -> Δ, or the band (4000, 8000) if PRF is missing
  fn azimuth_heading(meta) -> degrees            heading_deg, or approximated from orbit direction (issue 6)
  fn is_ghost(cand, img, heading, offset, tol_m = 200, db = 20) -> bool   search the image, both sides

detect/pboat
  fn features(cands, exposure) -> X              peak VV, peak VH, pol_agree, n_px, wind, ghost
  fn fit_pboat(injection_cands) -> model         statsmodels Logit
  fn predict_pboat(model, X) -> p_boat

detect/run
  fn run_pass(pass_id, img = None) -> candidates   public: validate.injection_test passes a modified chip
  fn run_all() -> detect/detections.parquet        drop candidates in cells where that pass is not calm

match/
  fn match(dets, gfw_sar, gate_m = 500) -> matched: bool   same pass; linear_sum_assignment, cost 1e9 beyond gate (issue 1)
  fn dark_small_events(dets) -> events             small + medium, unmatched, p = p_boat
  fn slowdowns_from_presence(presence2km, cells, era5) -> events
       cargo + tanker hours in the slowest bin (< 2 kn) > 0, outside exclusion, daily max hs < 4 m
       time = 12:00 UTC of the date; p = 1.0; duration_min = hours x 60; no ship_key (issue 3)
  fn slowdowns_from_tracks(ais) -> events         only if a track source appears (P4 per-ship rules)
  fn ship_key(ship_id) -> str                      salted SHA-256, salt from env
  fn write_events(...) -> match/events.parquet
```

### P5: aggregate/, forecast/

```text
aggregate/
  fn soft_counts(events) -> frame[cell_id, date, event_type, count]      sum of p
  fn exposure_rows(exposure, cells, dates) -> frame[..., exposure]        dark_small: sum exposure_small; slowdown: sea_frac, and 0 after GFW presence's latest date (A11)
  fn build_observed(counts, exposure) -> Observed                          full grid, E = 0 rows kept with C = 0
  fn to_coarse(observed) -> Observed                                       sum C and E over the 25 children
  -> aggregate/observed.parquet

forecast/
  fn ewma(observed, delta = 0.97, min_se = 3) -> mu       frozen at the cutoff, like the GLM (A7); parent rate x E until S_E >= 3
  fn design_matrix(cells, dates, event_type) -> X         inshore_frac (+ missing flag), lane, dist_coast, static_frac,
                                                          seasonal sin/cos for slowdowns only, intercept
  fn fit_glm(split, observed10, X) -> (beta, phi)         Poisson GLM, offset log E, scale "X2", train rows with E > 0
  fn empirical_bayes(O, M, phi) -> theta per 10 km cell   P5 formula; theta = 1 if the denominator <= 0
  fn predict_glm(beta, theta, X2km, E) -> mu
  fn nb_interval(mu, phi, level = 0.9) -> (lo90, hi90)
  fn poisson_deviance(C, mu) -> float
  fn backtest(event_type, model) -> table[fold, skill]    skill = 1 - D_model / D_flat
  fn choose_baseline(event_type) -> str                   appends a line to DECISIONS.md
  fn forecast_window(event_type) -> rows with fold = 0    fitted before the evaluation window only
  -> forecast/expected.parquet
```

### P6: detectors/, fuse/

```text
detectors/
  fn pearson_z(C, mu, phi) -> z                  (C - mu) / sqrt(max(phi, 1) * mu)
  fn tail_pmid(C, mu, phi) -> p_mid              negative binomial; interpolate between floor(C) and ceil(C) by the fractional part (A6)
  fn bh(p, q = 0.1) -> flags                     once over the whole evaluation window
  fn gi_star(C_week, mu_week, cells, band_m = 2900, perm = 999, seed) -> gi_z
  fn cusum(C, mu, phi, rho = 2, h) -> S          Poisson likelihood-ratio CUSUM (A1): S = max(0, S + (C ln rho - (rho - 1) mu) / max(phi, 1)); h from the simulator null; unobserved days leave S unchanged
  fn context_small(layers, post_storm) -> 0-1       NaN facts left out of the mean
  fn context_slowdown(layers, hours) -> 0-1      outside lanes; 0.33-3 slow hours (issue 3)
  fn fuse(scores) -> (U, agreement)              percentile ranks per event type over the window
  fn run_cells() -> fuse/cells.parquet

fuse/
  fn followup_exposure(s, exposure, nbrs, days = 7) -> X     window [date, date + 7] (issue 3)
  fn link_score(s, U_small, nbrs, tau = 3) -> L | None        None when X = 0, never 0; U_small = 0 on cell-days with C = 0 (A5)
  fn sites(slowdowns) -> site per 2 km cell                 no DBSCAN (A2)
  fn suppress(ranked_sites, radius_m = 4000) -> top list     drop a site within 4 km of a higher-ranked one (shown as "nearby")
  fn site_score(L, ages, half_life = 30) -> S
  fn link_table(U_small, exposure, nbrs, days = 7, tau = 3) -> arrays[cell, date]   precomputed best decayed U and X for every cell-date (A4)
  fn permutation(slowdowns, link_table, n = max(999, ceil(10 m / q)), shift_days = 60, seed) -> p_perm   m = sites tested (A3)
  fn recurrence(L_site, median_L) -> int
  fn pier_scores(sites, travel_hours, tau_h = 1) -> (P_j, top_piers)
  fn reasons(site, inputs) -> list[str]                       template; identity-free
  fn run(observed, expected, layers, travel, events) -> (cells, sites)   pure; validate.null_test calls it
  fn run_sites() -> fuse/sites.parquet
```

### P7: patrol/, export/, dashboard/

```text
patrol/
  fn sea_hours(nodes, sea, kn = 12) -> matrix          MCP_Geometric from each node
  fn air_hours(nodes, kn = 180) -> matrix               straight-line
  fn greedy_route(nodes, S, hours, budget_h, dwell_h) -> route
  fn two_opt(route, hours) -> route
  fn exploration_pick(sites_4_to_15, n_boot = 200, seed = seed + iso_week) -> site_id
  fn ship_plan() / fn aircraft_plan() -> patrol/plan.json

export/
  fn heatmap_values(expected, cells, exposure, week) -> per cell: 4 values + observed flag
  fn basemap(coastline) -> GeoJSON                      simplify(50) in metres, then WGS 84
  fn data_label(provenance) -> "simulated" | "real" | "mixed"
  fn build_snapshot(...) -> export/snapshot.json
  fn scan_identities(snapshot) -> None                 raise on stand-alone 9-digit numbers, IMO numbers, call signs; all times written as ISO strings (A12)

dashboard/ (index.html, plain JavaScript, inline SVG)
  loadSnapshot(), project(lon, lat), drawBasemap(), drawHeatmap(name, week), hatchUnobserved(),
  drawOverlays(), drawSiteList(), drawPlan(), drawValidation(), drawBanner(), onWeekChange(week)
```

### Make targets

```text
make sim       sim.simulate(config, seed)
make fetch     ingest.fetch_all(config)
make all       reference -> coverage.build_exposure -> detect.run_all -> match.write_events -> aggregate
               -> forecast -> detectors.run_cells -> fuse.run_sites -> patrol -> export.build_snapshot
make validate  validate.* -> reports/validation.json
make test      unit, schema, contract and identity tests
```

## Method map: best-fit model for every step

For each step, the method we use, the model the literature treats as standard, and the verdict. "Keep" means our choice is the standard one or the cheaper equivalent; "swap" means change it now (already done in the pseudo-codebase); "cut list" means don't build it unless the base is finished.

| Step | Our method | Standard model in the literature | Verdict | Risk to avoid |
| --- | --- | --- | --- | --- |
| Sea clutter threshold | Cell-averaging CFAR with a gamma tail, shape = ENL | Gamma fits homogeneous sea clutter; the K distribution fits heterogeneous, high-resolution clutter ([Stirling](https://www.stir.ac.uk/research/hub/file/1576309)). With shape set to the ENL, the gamma tail almost matches K ([Wilcoxon CFAR paper](https://arxiv.org/pdf/2402.18579)) | Keep: we only detect on calm passes (homogeneous); α is calibrated by injection anyway | Rough or patchy sea has heavier tails; never run small-boat detection on rough cells |
| Ghosts | Bright target 4–8 km along azimuth | Checking for a stronger target at the ambiguity displacement is a standard method ([Remote Sensing 2017](https://www.mdpi.com/2072-4292/9/8/866/htm)) | Keep | Heading guessed wrong: verify on one real ship |
| Is this a boat? | Logistic regression on candidate features, trained on injections | Platt-style logistic calibration | Keep | Injected Gaussian spots aren't real boats: check calibration on held-out injections, call p\_boat "model probability" |
| AIS matching | One-to-one assignment with a 500 m gate | Hungarian assignment (scipy linear\_sum\_assignment) | Keep, against GFW SAR detections (issue 1) | GFW SAR runs \~5 days behind: T is capped (A11) |
| Baseline A | Exposure-weighted EWMA rate | Poisson EWMA charts (Lucas and Saccucci) | Keep, frozen at the cutoff (A7) | Rolling into the scored days absorbs a repeated drop |
| Baseline B | Poisson GLM, offset log E, quasi scale, Gamma–Poisson empirical Bayes | Clayton–Kaldor empirical Bayes rate smoothing; NB2 GLM as the alternative | Keep; fit NB2 once as a check | Fitting on E = 0 rows; forgetting the offset |
| Intervals | Negative binomial, variance φμ | Same | Keep; add interval coverage check (A14) | Intervals that cover 60% look fine on a map |
| Cell surprise | Mid-p tail value | Lancaster mid-p | Keep, interpolated for soft counts (A6) | Rounding 0.4 boats to 0 hides weak evidence |
| Many tests | Benjamini–Hochberg, q = 0.1 | BH stays valid under positive dependence (Benjamini and Yekutieli 2001), which nearby cells have | Keep | Cell-level flags will be rare with 50,000 tests; that's expected. Sites are where flags matter |
| Neighbourhood | Getis-Ord Gi\* (esda) | For counts with expected values, the Kulldorff Poisson scan statistic | Keep Gi\* (library exists); scan statistic on the cut list | Gi\* with mostly zero cells: weekly sums and the stabilised ratio already handle it |
| Build-up | CUSUM on Pearson residuals | Poisson CUSUM ([Lucas 1985](https://par.nsf.gov/servlets/purl/10348944)), generalised to time-varying expected counts for small regional counts ([CDC](https://www.cdc.gov/mmwr/preview/mmwrhtml/su5301a18.htm)) | Swap (A1): likelihood-ratio Poisson CUSUM with target ratio ρ = 2 | z-scores of counts near 0 are badly skewed; the old CUSUM fires on single boats |
| Fusion | Mean of percentile ranks | Rank averaging; Fisher or Stouffer need independence | Keep | The four detectors share counts, so never call agreement a probability |
| Lag link | Slowdown followed by nearby small boats within 7 days | A bivariate space–time interaction test of the Knox type, counting pairs close in both space and time ([Knox method](https://www.nku.edu/~longa/geomed/stats/Knox/more.html)) | Keep our weighted form; pointpats.knox as a one-line global sanity check | Retuning radius or window after seeing results |
| Null for the link | Circular time shift of slowdowns | Random shift with toroidal wrap (Lotwick and Silverman 1982), which keeps each pattern's own structure while breaking the dependence between them ([arXiv](https://arxiv.org/pdf/1803.01639)) | Keep | Plain time shuffles break each series' own clustering and make links look too significant |
| Sites | DBSCAN on slowdown points | — | Swap (A2): one site per 2 km cell, plus suppression of near-duplicates | Slowdowns now sit on cell centres 2 km apart; DBSCAN at 3 km chains whole areas into one site |
| Site significance | 999 shuffles, BH across sites | Monte Carlo test | Keep, with enough shuffles (A3) | With 999 shuffles the smallest p is 0.001; BH over 300 sites needs 0.0003, so nothing could ever be flagged |
| Piers | Exponential decay with sea travel time | Gravity/accessibility decay | Keep | Straight-line distances across headlands |
| Routes | Greedy insertion + 2-opt | Standard orienteering heuristic | Keep | Exact solvers add a dependency for no visible gain at 15 nodes |
| Exploration | One draw per site from a bootstrap of its L | Thompson sampling | Keep | Unseeded draws change the plan mid-demo |
| Honesty | Wilson intervals, deviance skill, reliability and Brier, null test | Same | Keep, plus interval coverage (A14) | Tuning on the known Irish cases |

## Review passes and fixes (27 November, overnight)

Six passes over every function. Passes 1–3 found the issues below; pass 4 found the data-delay problem (A11); passes 5 and 6 found nothing new, so the review stopped. Where these differ from a module spec above, this table wins; the pseudo-codebase already includes them.

| # | Problem found | Fix | Module |
| --- | --- | --- | --- |
| A1 | CUSUM on Pearson z is wrong for counts near zero | Poisson likelihood-ratio CUSUM: S = max(0, S + (C ln ρ − (ρ − 1)μ) ÷ max(φ, 1)), ρ = 2; choose h on the simulator so a quiet cell alarms about once a quarter | P6 |
| A2 | DBSCAN chains adjacent cells into one giant site | A site is a 2 km cell; the top list drops any site within 4 km of a higher-ranked one | P6 |
| A3 | Too few shuffles for BH to ever flag a site | Test only cells with at least one linked slowdown (m of them); shuffles = max(999, 10m ÷ q) | P6 |
| A4 | Thousands of shuffles would be slow | Precompute, for every cell and date, the best decayed small-boat U and follow-up exposure in its 4 km neighbourhood; each shuffle is then a lookup | P6 |
| A5 | Tied ranks give every quiet cell-day U ≈ 0.45, so every slowdown earns some link score | U\_small = 0 on cell-days with C = 0 | P6 |
| A6 | Rounding soft counts throws away weak evidence | Interpolate the mid-p between floor(C) and ceil(C) | P6 |
| A7 | EWMA updating inside the scored window absorbs repeated drops | Freeze both baselines at the cutoff | P5 |
| A8 | ERA5 wave height is missing at grid points over land | Use the nearest grid point with valid wave data | P3 |
| A9 | P6's "after a storm" fact needs weather history it can't read | P3 writes post\_storm per cell and pass in coverage/exposure.parquet | P3, P6 |
| A10 | Any config change made every stage file stale, forcing a full rerun | Each stage hashes only the config keys it reads | P1 |
| A11 | GFW presence (\~3 days), GFW SAR (\~5 days) and ERA5 (\~5 days) lag the radar; the last days would count as "looked, saw nothing" | T = the earliest of the four latest dates; slowdown exposure is 0 after GFW's latest date. Say in the pitch that the system runs about 5 days behind | P1, P2, P5 |
| A12 | The identity scan would trip on timestamps stored as numbers | Match stand-alone 9-digit numbers only; write all times as ISO strings | P7 |
| A13 | 200 null runs × thousands of shuffles may not fit the weekend | Time one fuse.run on Friday; if over 30 s, use fewer runs and report the Wilson interval | P1 |
| A14 | Nothing checks whether the 90% intervals cover 90% | Add interval coverage to validation | P1 |

### Scope after the review

Removed: DBSCAN, per-ship slowdown rules (no track source; kept only as a fallback), Dawid–Skene (no third view), the exact ghost formula. Added: regrid\_presence, the post\_storm column, site suppression, the link table, interval coverage. The function count is roughly unchanged and no module gained a new input file.

### Top risks to avoid (in order)

1. **GFW is a single point of failure.** It supplies every slowdown. First test on Friday; if it fails, run on radar alone and drop the cargo-ship link from the pitch.
2. **The region mismatch.** Validated inshore maps cover the south-east, the known cases are in West Cork. Decide on Friday and write it in DECISIONS.md.
3. **Small boats under 10 m are often invisible at 20 m resolution.** Say so with the recall curve; never claim we see every boat.
4. **Unobserved shown as empty.** Every new data delay (A11) is a new way to break principle 4.
5. **Retuning after seeing results.** Radius, window, τ, q and the CUSUM target are fixed before real data, and changes go in DECISIONS.md.
6. **Compute time of the permutation and null tests.** Measure early (A13).
7. **Contract churn.** After Friday 22:00 a schema change needs the contract process below.

## Agent workflow

Each of the 7 people runs one or more agents on their own module; agents coordinate only through GitHub, never by editing each other's files.

### Repository layout

```
core/  sim/  validate/  reports/  P1
ingest/                       P2
reference/  coverage/         P3
detect/  match/               P4
aggregate/  forecast/         P5
detectors/  fuse/             P6
patrol/  export/  dashboard/  P7
data/<stage>/                 written only by the stage owner
config.yaml  Makefile  tach.toml  CODEOWNERS
DECISIONS.md  STATUS.md  AGENTS.md
<module>/CLAUDE.md            generated from that module's spec in this blueprint
```

### Work loop for an agent

1. Take one GitHub issue assigned to your module (issues are the job queue)
2. Work in a git worktree on branch `mod/<module>/<issue-number>`
3. Write the test first, against the simulator; then the code
4. Run `make test` locally (pre-commit runs ruff, the type checker and `tach check`)
5. Open a pull request using the template: what changed, which tests, **which warnings from your module spec you checked and how**
6. CI runs: unit tests, schema tests, contract tests on simulator files, path-ownership check (the PR may only touch your module's paths), Tach boundaries
7. The AI reviewer (Claude Code GitHub Action) reviews against this blueprint; it comments, it does not merge
8. Green CI + reviewer pass → auto-merge to `integration`; `make all` on the simulator runs there
9. A human merges `integration` into `main` at each checkpoint

### Stop and escalate rules

- **Three failed CI fix attempts on the same issue:** stop, label the issue `blocked`, write what you tried and the exact error, and wait
- **Missing information** (a number, name or API field this blueprint doesn't give): don't guess. Add a config key with `TODO(owner)`, open an issue labelled `question`, continue with the simulator
- **A change needed in another module or in `core`:** open an issue on that module; never edit it yourself
- **Discussion between agents** happens only in issue comments, at most 3 rounds per thread; then a human decides and records it in `DECISIONS.md`
- **Spend:** each agent has a token budget per session set by its human; overnight runs stop at the budget, not at "done"

### Shared files

- `DECISIONS.md`: every decision that changes a default, a contract or a principle, with date, who and why. Agents append; never rewrite
- `STATUS.md`: one line per module, updated at each merge: what works on the simulator, what works on real data, what's blocked
- `AGENTS.md`: the hard rules from "How to use this blueprint", copied verbatim

### Overnight runs (Friday and Saturday nights, during the event only)

- Only issues labelled `overnight-ok`: well-specified, tested on the simulator, inside one module
- Never overnight: contract changes, threshold tuning on real data, anything touching `export/` or the pitch
- A human reviews every overnight merge before 09:00

> **Warning:** passing lint, type checks and tests does not mean the statistics are right. Every PR touching a formula must say which simulator test recovers a known answer with it.

> **Warning:** all code must be written during the weekend (fresh-code rule). Agents must not paste in code from before Friday, including the prototype dashboard.

## GitHub setup, tools and token saving

How 7 people and their agents work in one repository without stepping on each other. Everything here is set up after the event starts on Friday (fresh-code rule).

### Who does what

| Person | Owns | Also |
| --- | --- | --- |
| P1 | core/, sim/, validate/, CI | Repo admin and integrator: merges integration into main at each checkpoint |
| P2 | ingest/ | Holds the data secrets; the only person whose agent has network access |
| P3 | reference/, coverage/ | Human check of exclusion zones on the map by Saturday 18:00 |
| P4 | detect/, match/ | Runs the ghost check on one real ship |
| P5 | aggregate/, forecast/ | Records the baseline choice in DECISIONS.md |
| P6 | detectors/, fuse/ | Times one fuse.run on Friday night (A13) |
| P7 | patrol/, export/, dashboard/ | Pitch, demo video, Sunday submission |

### Friday setup checklist (P1, first 90 minutes)

1. Create the repository; protect main and integration: pull request required, CI must pass, CODEOWNERS review for core/ and config.yaml, no force pushes
2. Turn on secret scanning and push protection
3. Add CODEOWNERS mapping each folder to its owner
4. Add labels: module:P1 … module:P7, contract, question, blocked, overnight-ok, bug, test
5. Add an issue template: module, blueprint section, function names from the pseudo-codebase, inputs, outputs, done-when test
6. Add a pull request template: what changed, which tests, which warnings from the module spec were checked and how
7. Commit pyproject.toml and uv.lock with the pinned packages below, config.yaml, Makefile, tach.toml, AGENTS.md, DECISIONS.md, STATUS.md, .env.example
8. Generate one issue per function group in the pseudo-codebase (about 60), each labelled with its module
9. Copy each module's blueprint section into \<module>/SPEC.md and write a short \<module>/CLAUDE.md that points to it
10. Add the three workflows below

### GitHub Actions

| Workflow | Runs on | Does |
| --- | --- | --- |
| ci.yml | every pull request | ruff, the type checker, pytest -q, tach check, schema and contract tests on simulator files, a path-ownership check (the PR may only touch its module's folders), the identity scan. Never uses the network or secrets |
| claude-review.yml | pull request opened or updated | anthropics/claude-code-action@v1 reviews the diff against \<module>/SPEC.md: warnings, Must not, test evidence for every formula. Comments only, never merges. Limit turns and use a smaller model to save tokens |
| claude.yml | @claude in an issue or PR comment | Answers questions and drafts fixes on request. The setup guide is in the [Claude Code docs](https://code.claude.com/docs/en/github-actions); the workflow needs an ANTHROPIC\_API\_KEY secret |

Use a concurrency group per PR so a new push cancels the old review.

### How agents work together

1. **One issue, one branch, one worktree:** mod/\<module>/\<issue>, created with git worktree add, so agents on the same laptop never share a working copy
2. **Agents talk only through stage files and listed public functions.** If you need something from another module, open an issue on it; never edit it
3. **Stubs first.** By Friday 22:00 every module has every public function from the pseudo-codebase as a stub that returns schema-valid simulator output, so make all runs end to end on Saturday 02:00
4. **Contract change process:** an issue labelled contract → P1 and every affected owner approve in comments → one PR changes core/schemas and the Data dictionary together → everyone rebases
5. **Merges:** green CI + review comments addressed → auto-merge to integration; a human merges integration into main at each checkpoint
6. **Status:** each merge updates the module's line in STATUS.md; decisions go in DECISIONS.md (append only)

Checkpoints: Friday 22:00 contracts frozen · Saturday 02:00 stubs run end to end · Saturday 12:00 real data cached, dashboard on the simulator · Saturday 18:00 human map checks · Saturday 22:00 real snapshot · Sunday 10:00 demo video · Sunday 13:00 code freeze · Sunday 15:00 submit.

### Agent guard rails (in each module's .claude/settings.json)

- **Permissions:** allow edits only inside the module's folders and its tests; deny web fetches and network commands everywhere except ingest/
- **Hooks:** a pre-edit hook that rejects writes outside the module's paths; a post-edit hook that runs ruff format
- **Session hygiene:** one issue per session; clear the context between issues; stop at the token budget set by the human

### Tools to install (everyone, Friday)

| Group | Install |
| --- | --- |
| Basics | git, GitHub CLI (gh), uv, Python 3.12, Claude Code |
| Quality | ruff, basedpyright (or mypy), pytest, pre-commit, tach, pandera |
| Data and maths | numpy, scipy, pandas, pyarrow, statsmodels, scikit-image, libpysal, esda, pointpats |
| Geo | geopandas, shapely, pyproj, rasterio, rioxarray, xarray, netCDF4 |
| Data access (P2 only) | openeo, gfw-api-python-client, cdsapi, requests (for Overpass) |
| Agent helpers | Serena (below); optionally one code-graph tool |

scikit-learn is no longer needed (DBSCAN was cut). Pin every version in uv.lock on Friday and never upgrade during the weekend.

### Token saving

In rough order of payoff for a small repository:

1. **Small context by design.** Each agent reads only its SPEC.md, the schemas in core/schemas and the stage files it consumes; never the whole blueprint or other modules' code. This saves more than any tool
2. **Tach as a free map.** tach report \<module> lists what a module imports and who uses it; tach check stops boundary violations before review ([Tach](https://github.com/gauge-sh/tach))
3. **Serena.** An MCP server that gives agents symbol-level lookups and edits through a language server instead of reading whole files ([Serena](https://pkg.go.dev/github.com/oraios/serena)). Its makers note the benefit is smaller on very small projects, so install it but don't depend on it
4. **A code graph (optional, Saturday only if tokens run short).** For example codebase-memory-mcp, which parses the code with tree-sitter into a SQLite graph of functions, calls and imports exposed as MCP tools ([dev.to](https://dev.to/deusdata/how-i-cut-my-ai-coding-agents-token-usage-by-120x-with-a-code-knowledge-graph-4a3d)), or code-review-graph, which installs with pip ([GitHub](https://github.com/juspay/code-review-graph-rescript)). Their benchmarks are on large repositories; ours will be a few thousand lines, so pick one at most
5. **Quiet commands.** pytest -q --tb=short, make targets that print one line per stage, and no printing of data frames
6. **Right model per job.** The strongest model for P4 and P6 maths; a smaller one for the reviewer, stubs and dashboard plumbing

> Warning: agents running overnight with broad permissions are the biggest token and damage risk of the weekend. Only issues labelled overnight-ok, inside one module, with a human review before 09:00.

## Failure catalogue and cut list

### The five silent traps (the pitch slide)

Each produces clean, plausible, wrong results. Each is designed out, not just tested for.

| Trap | What goes wrong | How it is designed out | Owner |
| --- | --- | --- | --- |
| Unobserved as zero | Quiet cells look empty, busy cells look suspicious | `core.Observed`; schema rejects count > 0 with exposure 0; unobserved drawn hatched | P1, P5, P7 |
| Look-ahead leakage | Backtest looks excellent and means nothing | `core.Split` with a 7-day embargo; future-row test in CI | P1, P5 |
| Rough seas read as empty | Storm days look like no boats | Rough passes get small-boat exposure 0 | P3 |
| Radar ghosts and fixed objects | Ghosts and turbines become "dark boats" | Ghost rule, static mask, coastal buffer, injection-measured false alarms | P3, P4 |
| Busy areas create chance links | Lanes and fishing grounds produce fake drop sites | Exclusion zones, inshore baseline, circular-shift permutation test | P3, P6 |

### Other failures to watch

| Failure | Where | Guard |
| --- | --- | --- |
| Fresh-code rule broken (pre-written code) | All | Write everything from Friday; confirm the rule at the opening |
| Real data late or missing | P2 | Friday probe; simulator keeps everyone going; honest `data_label` |
| Most pick-ups happen between passes | P4, P6 | Score recurring sites; show `followup_unobserved`; state recall |
| Legitimate ship stops (pilots, berths, weather) | P3, P4 | Exclusion zones checked by a human; storm filter; never flag a slowdown alone |
| Unmapped coast treated as "outside fishing grounds" | P3, P6 | `inshore_frac = NaN` where unknown; context rule skips unknown facts |
| Only 90 days of small-boat radar | P5 | No seasonal terms for `dark_small`; use 6 weekly folds for that type instead of 12 |
| Multiple testing floods the list | P6 | One Benjamini–Hochberg pass over everything; parameters fixed before real data |
| Tuning to the known Irish cases | P1, P6 | Sanity list only; any retune logged in `DECISIONS.md` |
| Coordinate or time-zone mix-ups | All | One CRS and UTC enforced in `core` |
| Identities leaking into the demo | P4, P7 | Salted `ship_key`; identity scan of the snapshot |
| Venue internet fails | P7 | Offline dashboard; recorded video |
| Agents loop or overrun budget | All | Stop after 3 CI failures; 3-round discussion cap; token budgets |

### Cut list (deliberately not built, and why)

| Idea | Why it is cut |
| --- | --- |
| Wake detection and heading cones | Pick-up boats are slow local boats; wakes mainly help with fast go-fasts and fail in rough seas |
| AIS spoofing detection | Already done commercially (Lloyd's List Intelligence, Global Fishing Watch); not our gap |
| Land change detection at coves | Narrow tracks are below 10–20 m resolution; slow signal; extra data volume |
| Moran's I against seizure news | Too few local events; collecting the news costs time |
| Back-tracking washed-up bales with ocean currents | Good idea, but a separate project; needs current data and a drift model |
| Training our own detector or CNN | No labels and no time; CFAR plus calibration does the job |
| LightGBM residual corrector, foundation-model search | Adds complexity without a measured gain |
| Hawkes process, space-time scan statistic | Overlap with CUSUM, Gi\* and the lag link |
| A live pipeline | The demo runs on cached data; a weekly refresh script is a stretch goal only |
| Conformal prediction intervals | Duplicates the negative binomial intervals, whose coverage P1's calibration check already tests. Allowed only as a P5 stretch goal if that check shows the intervals are badly off |
| Log-likelihood ratio fusion of signals | Needs calibrated inputs we don't have; replaced by percentile-rank fusion (U) and the lag link (L) |
| Random walk with drift and Kalman filter for boat motion | Needs repeated sightings of the same boat, which snapshot imagery doesn't give; replaced by sea-only travel times to piers |

Agents must not add any of these without a human editing this list.

## Research on open questions (27 November)

Two findings change the plan: GFW loitering events can't supply our slowdowns, and the validated inshore maps cover the south-east coast, not West Cork. Everything below is from the linked pages; anything still unconfirmed says so.

| Question | Finding | Status | What changes |
| --- | --- | --- | --- |
| GFW loitering for cargo ships near the coast | The Events API has loitering for all vessel types and a vessel-type filter ([Events API](https://globalfishingwatch.org/our-apis/documentation/docs/v3/events)), but published loitering is restricted to an average distance from shore of at least 20 nautical miles, about 37 km ([GFW technical docs](https://globalfishingwatch.github.io/GFW_technical_documentation/files/loitering.html)) | Answered: not usable | Our band is 0–25 km, so no loitering events will fall in it. P2 and P4 now use GFW AIS presence instead (below) |
| Slowdowns from GFW AIS presence instead | public-global-presence:latest has filters for flag, vessel type and speed range in knots, built from one position per hour per vessel ([4Wings](https://globalfishingwatch.org/our-apis/documentation/docs/v3/4wings)) | Partly answered | A slowdown becomes "cargo or tanker presence-hours below 2 knots in a cell-day, outside exclusion zones". No per-ship duration or identity. Test the filters on Friday |
| Marine Institute AIS dataset | It is vessel-density rasters on a 1 km grid built from 2017 AIS, by ship type, served as a map service; no licence named ([catalogue](https://data.marine.ie/geonetwork/srv/api/records/ie.marine.data:dataset.3991)) | Answered: not tracks | Useful only as a cross-check for lanes. There is no open Irish AIS track source in the plan |
| GFW licence and prize | API use is non-commercial only under CC BY-NC 4.0, with attribution such as "Powered by Global Fishing Watch" ([licence](https://globalfishingwatch.org/our-apis/documentation/docs/license-rate-limits)); commercial products need a custom licence, which GFW may grant when clearly mission-aligned ([FAQ](https://globalfishingwatch.org/faqs/can-i-use-global-fishing-watch-apis-for-commercial-purposes/)) | Partly answered | A free public-good prototype fits the licence; whether a cash prize or later startup does is a question for the organisers and GFW. Add the attribution line to the dashboard |
| Equivalent number of looks | ESA lists ENL 4.4 for IW GRD high resolution ([ESA](https://sentinel.esa.int/web/sentinel/user-guides/Sentinel-1-sar/resolutions/level-1-ground-range-detected)) | Answered | P4 starts with L = 4.4, still checked on calm sea |
| Ghost offset | Typical spaceborne azimuth-ambiguity displacements are 4–8 km, and checking for a stronger target at that displacement is a standard method ([Remote Sensing 2017](https://www.mdpi.com/2072-4292/9/8/866/htm)). With an example IW scene's PRF of about 1,717 Hz, the formula gives about 5.5 km (my arithmetic) | Partly answered | If scene metadata isn't available, search 4–8 km along azimuth; still verify on one real ship |
| Pass times | Sentinel-1's local time at the ascending node is 18:00 ([SentiWiki](https://sentiwiki.copernicus.eu/web/s1-mission)), so passes come around 06:00 and 18:00 local solar time | Answered | Night pick-ups between passes are never imaged. Say so in the pitch; it strengthens "find the drop, not the boat" |
| openEO names | CDSE openEO uses load\_collection with id SENTINEL1\_GRD; backscatter needs the sar\_backscatter process, which supports beta0, sigma0-ellipsoid and gamma0-ellipsoid, not terrain-flattened gamma0 ([CDSE forum](https://forum.dataspace.copernicus.eu/t/download-s1-grd-data/3151)); it can't run as a synchronous request, so use batch jobs ([CDSE forum](https://forum.dataspace.copernicus.eu/t/to-get-all-out-of-openeo-we-need-sentinel-1-ard/3130)) | Mostly answered | P2 requests sigma0-ellipsoid via batch jobs. Annotation metadata (PRF) is not provided by openEO; use the 4–8 km fallback |
| Inshore map coverage | BIM's validated maps come from Wexford and Waterford ports plus two east Cork ports; the combined maps and dataset are on Zenodo, individual fishery maps are not public ([The Skipper](https://theskipper.ie/bim-maps-where-inshore-boats-fish/)) | Answered | West Cork, where the known cases are, has no validated map. Decide on Friday: move the region east (Ballycotton to Wexford) or use Marine Institute layers in the west. Check the Zenodo licence |
| Data cube | Participants get a Copernicus data cube limited in area and time, pre-processed for the theme ([CASSINI FAQ](https://hackathons.cassini.eu/contact)), plus CDSE storage and compute for the weekend ([CASSINI tools](https://www.cassini.eu/hackathons/tools)) | Open | Ask at the opening which area and dates it covers; if it includes the south coast, P2 starts there |
| Fresh-code rule, judging criteria | The 12th edition's rules page could not be reached; past editions required fresh code; IP stays with the team ([CASSINI FAQ](https://hackathons.cassini.eu/contact)) | Open | Ask the organisers at the opening |
| Galileo OSNMA | Declared operational on 24 July 2025 and free; receivers must implement the protocol and fetch public keys from the GNSS Service Centre ([EUSPA](https://www.euspa.europa.eu/newsroom-events/news/testing-operations-galileo-osnma-service-now-available-users)) | Answered | The Galileo slide is factual; it needs an OSNMA-capable professional receiver on the patrol boat, not a phone (phone support unconfirmed) |
| Start time | The 12th hackathon starts Friday 27 November at 18:00 ([CASSINI](https://www.cassini.eu/hackathons/)); the time zone isn't stated, probably CET (17:00 in Ireland) | Check | Confirm the local agenda from NCI |

## Open questions

Agents must not guess any of these; each has an owner who answers it and records the answer in `DECISIONS.md`.

**For the organisers (human, Friday opening)**

- [ ] Does the fresh-code rule apply to the 12th edition, and does a plan written beforehand count as code?
- [ ] Does Global Fishing Watch's non-commercial licence conflict with a cash prize or later mentoring?
- [ ] What is in this edition's data cube, and does it give faster Sentinel-1 access than Copernicus Data Space?
- [ ] What are the judging criteria for the 12th edition?
- [ ] Does a Galileo OSNMA slide count as a valid use of Galileo for this challenge?

**To test on Friday (P2, P4, P3)**

- [ ] Exact openEO or Sentinel Hub names for calibrated, terrain-corrected Sentinel-1 GRD, and whether the annotation metadata (PRF, slant range) is reachable (P2)
- [ ] Whether GFW events include loitering by cargo ships and tankers in Irish waters (P2)
- [ ] Coverage, dates and licence of the Marine Institute AIS dataset (P2)
- [ ] Typical Sentinel-1 pass times over the south coast (P2)
- [ ] The ghost offset on one real scene with a known bright ship (P4)
- [ ] Equivalent number of looks of the GRD product on calm sea (P4)
- [ ] Where the BIM and Marine Institute inshore maps end along the coast (P3)

**To tune on the simulator and injection tests (never on known cases)**

- [ ] Calm thresholds (wind 6 m/s, waves 1.5 m) (P3)
- [ ] CFAR false-alarm setting and the detection-probability model (P4)
- [ ] Slowdown speeds and duration (P4)

Sources for the facts in this tab are linked inline in Mission and context, and in the Plan tab's Unknowns section.
