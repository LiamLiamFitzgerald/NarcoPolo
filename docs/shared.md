<!-- Generated from the Agent blueprint (rev 108, 27 Nov 2026). Do not edit here: change the blueprint, then regenerate. -->

# Shared context for every agent

Read this once per session, then only your own spec in docs/specs/.

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
| `reference/layers.gpkg` closed\_areas layer (P3 writes, P6 and P7 read; #322) | `area_id` str; `name` str (the published area name); `type` {closure, protected\_area}; `start_date`, `end_date` date or NaT (where published); `geometry` (multi)polygon, EPSG:32629; start\_date ≤ end\_date. P6 decides per 2 km cell whether it lies in an area; no layer means unknown (NA), never "outside" | tens |
| `reference/sea_250m.tif` (P3) | uint8: 1 sea, 0 land | about 750 × 380 px (the whole bounding box, land included) |
| `reference/travel_hours.parquet` (P3) | `cell_id`, `pier_id`, `hours` float | cells × piers, \~50k |
| `reference/presence_2km.parquet` (P3, read by P4; #208) | `cell_id` str (in reference/cells); `date` date (UTC); `vessel_type` str (as in raw/gfw\_presence); `speed_bin` str (GFW's label, e.g. "0-2", "8+"); `hours` float ≥ 0 (area-weighted); one row per cell, date, type and bin | \~10⁵ |
| `coverage/weather_daily.parquet` (P3, read by P4; #208) | `cell_id` str (in reference/cells); `date` date (UTC); `wind_max_ms` float ≥ 0; `hs_max_m` float ≥ 0: max over the UTC day's hourly ERA5, with coverage.weather\_at's point rules (nearest point for wind, nearest valid-wave point for waves, A8); one row per cell-day; no row where ERA5 is unknown (never 0) | cells × days, \~10⁵ |
| `coverage/exposure.parquet` (P3) | `cell_id`, `pass_id`, `time_utc`, `covered_frac` 0–1, `wind_ms`, `hs_m`, `calm` bool, `exposure_small` float 0–1, `post_storm` bool (≥ 24 h of hs > 2.5 m in the 72 h before the pass, A9) | \~60 passes × \~940 cells, \~56k |
| `detect/detections.parquet` (P4) | `det_id`, `pass_id`, `time_utc`, `x_m`, `y_m`, `peak_ratio_vv_db`, `peak_ratio_vh_db`, `pol_agree` bool, `n_px` int, `size_class` {small, medium, large}, `ghost` bool, `p_boat` float 0–1 | tens to hundreds per pass |
| `match/events.parquet` (P4) | `event_id`, `event_type` {dark\_small, dark\_medium, slowdown} (dark\_medium: unmatched detections with size\_class medium, `p` = p\_boat, no ship\_key, #344), `time_utc`, `x_m`, `y_m`, `cell_id`, `p` float 0–1, `duration_min` (slowdowns), `ship_key` (salted hash, internal only), `matched` bool | thousands |
| `validate/pboat_training.parquet` (P1 `validate.injection_test`, read by P4 `fit_pboat`; #209) | `pass_id`, `cell_id` str (in reference/cells), `date` date (the chip's UTC date), `peak_ratio_vv_db`, `peak_ratio_vh_db` float, `pol_agree` bool, `n_px` int ≥ 1, `ghost` bool (as `detect.run_pass` gives them), `label` bool: True = candidate at an injected boat, False = candidate in the same chips > 500 m from any injection or AIS ship (candidates in between are left out). P4 joins `wind_ms` from coverage/exposure on (cell\_id, pass\_id) and refits on every `detect.run()` with the shared `core.Split`; no fitted model is stored | hundreds to thousands |
| `aggregate/observed.parquet` (P5) | `cell_id`, `level`, `date`, `event_type` (as in match/events; dark\_medium uses the same calm-pass exposure as dark\_small, #345), `count` float ≥ 0, `exposure` float ≥ 0 | \~690k slowdown + \~85k small, \~770k |
| `forecast/expected.parquet` (P5) | `cell_id`, `date`, `event_type`, `mu` float, `phi` float, `lo90`, `hi90`, `model` str, `fold` int; dark\_medium rows fitted like dark\_small (#345) | same as observed |
| `fuse/cells.parquet` (P6) | `cell_id`, `date`, `event_type`, `p_mid`, `bh_flag` bool, `gi_z`, `cusum_s`, `context` 0–1, `U` 0–1, `y` float ≥ 0 = (C + 0.5) ÷ (μ + 0.5), `y_week` float ≥ 0 = (ΣC + 0.5) ÷ (Σμ + 0.5) over the cell's ISO week, `agreement` 0–4 | same as observed, observed rows only |
| `fuse/sites.parquet` (P6) | `site_id`, `x_m`, `y_m`, `n_slowdowns`, `S` float, `p_perm`, `bh_flag` bool, `recurrence` int, `followup_unobserved` int, `agreement` 0–4, `reasons` list\[str\], `top_piers` list\[str\] | tens |
| `fuse/piers.parquet` (P6) | `pier_id` str (in the piers layer), `P_j` float ≥ 0 = Σ over scored sites of S × exp(−T ÷ 1 h) | one row per pier |
| `fuse/links.parquet` (P6) | `site_id` str (in fuse/sites), `L` 0–1, `age_days` float ≥ 0; per site, Σ L × 0.5^(age\_days ÷ 30) = S | one row per slowdown with a link score |
| `fuse/sites.parquet` learning columns (P6, optional until the learning layer lands; docs/learning.md) | `p_comb` 0–1, `comb_flag` bool, `agreement_merged` int ≥ 0, `p_site` 0–1, `model_rung` 0–3 | same rows as fuse/sites |
| `fuse/sites.parquet` briefing-card columns (P6, optional; #320) | `check_rare_slowdown` bool, `check_followup_seen` bool, `check_outside_fishing` bool or NA (NA where no inshore map exists), `top_piers_hours` list\[float\] ≥ 0, same length as `top_piers` | same rows as fuse/sites |
| `fuse/fisheries.parquet` (P6 writes, P7 reads; #321, #346) | `cell_id` str (2 km); `week` date (the Monday); `count`, `mu` float ≥ 0 (the week's dark\_medium soft count and expected count); `y_fish`, `y_fish_lo`, `y_fish_hi` float ≥ 0 = (count + 0.5) ÷ (mu + 0.5), with the range from the 90% interval (lo ≤ hi); `p_mid` 0–1 (mid-p tail of the weekly count); `flag` bool (BH at fdr\_q across all cell-weeks); `in_closed_area` bool or NA (NA where the closed\_areas layer is missing); `reasons` list\[str\]; `top_harbours` list\[str\] (pier ids); `top_harbours_hours` list\[float\] ≥ 0, same length as `top_harbours`; `lens` "fisheries" | one row per candidate cell-week, tens |
| `patrol/bandit_state.json` (P7) | `{site_id: {alpha > 0, beta > 0, last_visit_week int or null}}`; plan stops may carry `theta` 0–1 and `reason` exploit/explore | one entry per site ever ranked |
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
| Getis-Ord Gi\* (analytic z) | P6 | Neighbourhood hotspots | own code, tested against `esda.G_Local(star=True)` (D6) | Non-negative variable; weights skip unobserved cells | Unobserved cells treated as zero neighbours |
| CUSUM | P6 | Slow build-ups | own code | Residuals roughly standardised | Updating on unobserved days |
| Percentile-rank fusion | P6 | Combine detectors on one scale | `pandas.rank(pct=True)` | Ranks over the same set of cells | Ranking over different cell sets skews U |
| Exponential time decay | P6 | Favour quick pick-ups and recent events | own code | Pick-ups follow within days | — |
| Circular time-shift permutation test | P1, P6 | Site significance; null test | own code | Shifting breaks timing but keeps busyness | Too few shuffles give unstable p-values |
| Minimum-cost path on a sea raster | P3, P7 | Sea-only distances | `skimage.graph.MCP_Geometric` | Land cost infinite | A gap in the coastline lets boats cross land |
| Greedy orienteering + 2-opt | P7 | Route within a time budget | own code | Travel times correct | Straight-line distances cut across headlands |
| Thompson sampling (bandit, docs/learning.md L5) | P7 | Pick which sites to visit and explore | `numpy` | Resampled scores reflect uncertainty | Unseeded draws make the demo change every run |
| Wilson score interval | P1 | Recall uncertainty | `statsmodels` `proportion_confint` | Binomial counts | — |
| Reliability diagram and Brier score | P1 | Check probability calibration | own code or `sklearn.calibration` | Enough held-out events | Too few events per bin: merge bins |
| Injection test | P1 | Measure detection recall and false alarms | own code | Injected blobs resemble real boats | Adding in dB instead of linear power |


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
| Lag link | Slowdown followed by nearby small boats within 7 days | A bivariate space–time interaction test of the Knox type, counting pairs close in both space and time ([Knox method](https://www.nku.edu/~longa/geomed/stats/Knox/more.html)) | Keep our weighted form (Knox check not built, methods audit D5) | Retuning radius or window after seeing results |
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
