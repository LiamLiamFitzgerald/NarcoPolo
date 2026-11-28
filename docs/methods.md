<!-- Methods audit, 28 Nov 2026 01:45. Every statistical method in NarcoPolo: why it is there, where it lives, and whether it is used as intended. Source of truth for formulas: docs/shared.md (Measures, Statistical methods index, Method map) and docs/learning.md. -->

# Methods audit: every statistical method, and whether it earns its place

**Rule:** a method stays only if it answers a question nothing simpler answers, and its "how it fails silently" risk is checked by a test.

**Status key:** ✅ used as specified · ⚠️ used, with a concern to decide · ✂️ documented but not used (remove or build) · 🆕 learning layer (docs/learning.md), not yet on integration unless noted

---

## 1. Seeing boats (P4, radar)

| Method | Why it's there | Where | Status |
| --- | --- | --- | --- |
| Cell-averaging CFAR with guard ring | A boat is a pixel brighter than its local sea; the ring estimates "local sea" | `detect/cfar.py` (`uniform_filter`) | ✅ Calm passes only, so the homogeneous-clutter assumption is reasonable |
| Gamma threshold from equivalent looks | Sets the threshold for a target false-alarm rate instead of guessing a dB value | `detect/cfar.py` (`gamma.isf`) | ✅ Real clutter has heavier tails; the injection test measures the real false-alarm rate |
| Connected components (8-neighbour) | One boat = one blob | `detect/cfar.py` (`ndimage.label`) | ✅ |
| VV/VH one-to-one matching with a gate | Pairs the same target in both polarisations (agreement feature) | `detect/cfar.py` (`linear_sum_assignment`) | ✅ |
| Azimuth-ambiguity ghost rule | Removes radar "ghosts" of bright ships that would look like dark boats | P4 ghost code | ✅ Verify the offset on one real ship |
| Logistic regression → `p_boat` | Turns detection features into a probability | `detect/pboat.py` | ⚠️ Trained on injected Gaussian spots, which are not real boats; call it a "model probability" and check calibration on held-out injections |
| Dawid–Skene EM | Combine 3+ detector views without labels | — | ✂️ Not used. Remove from the index |

## 2. Turning detections into events (P4, match)

| Method | Why | Where | Status |
| --- | --- | --- | --- |
| Hungarian assignment with a gate (detections ↔ GFW SAR) | Separates AIS-carrying ships from "dark" detections, one-to-one | `match/events.py` | ✅ |
| Linear interpolation of AIS positions | AIS position at scan time | — | ✂️ Not used: slowdowns come from GFW gridded presence, not tracks (`slowdowns_from_presence`). Remove from the index, or keep only if a track source appears |
| Rolling median speed + threshold | Ship slowdown events | `match/events.py` | ✅ Exclusion zones (ports, anchorages) remove legitimate stops |

## 3. What normal looks like (P5)

| Method | Why | Where | Status |
| --- | --- | --- | --- |
| Exposure-aware EWMA | Simplest baseline that adapts over time; also the "flat-ish" challenger | `forecast/__init__.py` | ✅ Unobserved days don't count as zeros; parent shrinkage (#58) removes μ = 0 |
| Quasi-Poisson GLM with `log E` offset | Uses cell covariates (lanes, anchorage, distance to coast) so busy places aren't "unusual" just for being busy | `forecast/__init__.py` (`scale="X2"`, `offset=`) | ✅ Fitted on 2 km rows with E > 0 (#58). ⚠️ Slowdown skill was −0.12 vs +0.43 for EWMA on the simulator; keep it only while it wins somewhere (dark_small: +0.20) |
| Empirical Bayes Gamma–Poisson shrinkage | Stops one stray boat making a sparse cell a "hotspot" | `forecast/__init__.py` | ✅ |
| NB2 fit as a check | Confirms the quasi-Poisson dispersion is in the right range | `forecast/__init__.py` (`nb2_alpha`) | ⚠️ Raises a convergence warning on the simulator; it's a check, so log it, don't let it block |
| Negative binomial predictive interval | Honest ranges (lo90/hi90) | `forecast/__init__.py` | ✅ Coverage measured: 0.988 vs 0.90 target, i.e. **too wide**. Worth asking why (φ overestimated?) |
| Walk-forward splits, 7-day embargo | Honest backtest: the future never informs the past | `core/split.py` | ✅ |
| Poisson deviance skill | Is the model better than "same as average"? | `forecast`, `validate/backtest.py` | ✅ Reported as mean/min/max over folds |

## 4. How unusual is a cell (P6, detectors)

| Method | Why | Where | Status |
| --- | --- | --- | --- |
| Pearson residual z | Comparable surprise across cells | `detectors/scores.py` | ✅ Uses max(φ, 1) |
| Mid-p negative binomial tail | Per-cell "this many or more" probability, exact for small counts | `detectors/scores.py` | ✅ Soft counts interpolated, never rounded (A6) |
| Benjamini–Hochberg (q = 0.1) | Controls false flags over thousands of cells | `detectors/scores.py` | ✅ Once over the whole window, never per subset |
| Getis-Ord Gi* on y | Neighbourhood hotspots (a spot plus its neighbours high together) | `detectors/scores.py` | ⚠️ Own code, not `esda`, although the docstring says "this is esda.G_Local". Fine if a test checks it against esda on a small grid; otherwise fix the docstring. `perm`/`seed` parameters are unused |
| Poisson likelihood-ratio CUSUM (ρ = 2) | Slow build-ups over days | `detectors/scores.py` | ⚠️ Threshold `cusum_h = 0.5` is "a pick, not a fit" (code comment, #124), and the increment is divided by max(φ, 1), which is not in A1. Decide both |
| Context score | Unusual for its setting (yes/no facts) | `detectors` | ✅ |
| Percentile-rank fusion → U | One 0–1 score per cell-day from four detectors | `detectors/scores.py` (`rank(pct=True)`) | ⚠️ **Overlaps with p_comb** (section 6). U still feeds the link score L; see decision D1 |
| Agreement badge (0–4) | How many detectors agree | `detectors` | ⚠️ Double-counts: three of the four share the same counts. Superseded by `agreement_merged` for display (D1) |

## 5. Linking and sites (P6, fuse)

| Method | Why | Where | Status |
| --- | --- | --- | --- |
| Lag link (slowdown → small boats within 7 days, decayed) | The drop-off pattern itself: ship slows, small boat visits | `fuse/link.py` | ✅ Weighted Knox-type test. ✂️ The `pointpats.knox` global sanity check in the method map isn't built |
| Follow-up exposure X | Could we have seen a pick-up at all? Avoids "no pick-up seen" meaning "none happened" | `fuse/link.py` | ✅ |
| Exponential time decay (30-day half-life) | Recent behaviour matters more | `fuse/link.py`, `fuse/_common.py` | ✅ Spec constant, not fitted; fine, but don't retune after seeing results |
| Circular time-shift permutation (site p) | Could busy traffic alone explain this site? | `fuse/link.py` (#169) | ✅ n ≥ ceil(10m/q) shuffles (A3), so BH can flag anything at all |
| One site per 2 km cell + suppression | Sites without DBSCAN chaining | `fuse/link.py` (#169) | ✅ DBSCAN correctly dropped (A2) |
| Recurrence count | Is the spot reused? | `fuse/link.py` | ✅ |
| Pier score (decay with sea travel time) | Which piers to watch | `fuse` (`fuse/piers`) | ✅ |
| Minimum-cost sea path | Sea-only travel times | `reference/piers.py`, `patrol` (`MCP_Geometric`) | ✅ Check the coastline has no gaps |

## 6. Learning layer (docs/learning.md)

| Method | Why | Where | Status |
| --- | --- | --- | --- |
| Per-signal walk-forward backtests | Know what each signal is worth on its own | `validate/signals.py` (#153) | 🆕 Not started |
| Cohen's κ / Spearman ρ + merge rule | Signals that say the same thing get one vote | `validate/signals.py` (#153) | 🆕 Not started; threshold `merge_kappa` is a TODO |
| Null samples → site p = (1 + #null ≥ s) ÷ (1 + n) | Turns any score into a calibrated p | `fuse/combine.py` (#160) | 🆕 Correct formula; needs null-regime runs (#150, #153) |
| Cauchy combination test (CCT) | Combines correlated p-values validly (Fisher/Stouffer need independence) | `fuse/combine.py` (#160) | 🆕 Anti-conservative 10–25% under positive correlation → calibrated threshold |
| Null-run threshold calibration | Fixes CCT's anti-conservatism | `fuse/combine.py` (#160) | 🆕 Needs the `null` regime |
| Regret-weighted votes (attention) | Signals aren't equally useful; weight by how much regret rises without them | L3 4a / L6 step 6 | 🆕 Rev 2. τ and floor are tuning knobs: set on **train** regimes only |
| Non-negative ridge logistic stack (rung 1) | Learns how much to trust each signal, monotone and readable | `validate/train.py` (#166), `fuse/learn.py` (#160) | 🆕 Format mismatch to fix (R3, R4) |
| Neural Additive Model (rung 2) | Flexible but still one readable curve per signal | `validate/train.py` (#166) | 🆕 Only if n_eff ≥ 500 and it beats rung 1 on held-out regimes |
| Mixture of experts (rung 3) | Trust different signals in different conditions | — | ✂️ Nobody is building it. Cut list |
| Promotion rule (gain > 2 SE, Brier not worse) | A learned piece ships only if it wins | `validate/train.py` (#166) | 🆕 |
| Beta–Bernoulli Thompson sampling with discount | Learns which sites pay off, explores where unsure, forgets old evidence | `patrol/bandit.py` (#159) | 🆕 |
| Exact orienteering (DP over subsets) | Combinatorial TS needs an exact route solver | `patrol/__init__.py` (#159) | 🆕 ≤ 16 sites |
| Greedy insertion + 2-opt | Fallback above 16 sites; also the old planner | `patrol/__init__.py` | ✅ |
| Bootstrap exploration slot | Old exploration: one draw per site from its bootstrapped L | `patrol` | ⚠️ Replaced by Thompson draws when the bandit runs; remove once #159 merges (D3) |
| Time-expanded orienteering (site × day) | When to go matters: pass-aware drops hide in satellite gaps | L5 step 7 | 🆕 Rev 2, not started |
| Season knapsack over weekly hours | Spread hours to uncertain weeks | L5 step 8 | ⚠️ A simple rule, not a solver: keep only if it lowers regret in L6 (D4) |
| Expected-regret exploration | Explore what you'd most regret missing | L5 step 9 | 🆕 Rev 2 |
| Pseudo-regret vs oracle, weeks to first find, finds per patrol-hour, coverage entropy | Proves (or disproves) that learning patrols beat a fixed ranking | `validate/policy.py` (#157) | 🆕 |

## 7. Honesty checks (P1, validate)

| Method | Why | Where | Status |
| --- | --- | --- | --- |
| Injection test | Real detection recall and false alarms, in linear power | `validate/injection.py` | ✅ Recall 0 / 0.02 / 1 / 1 at 3 / 6 / 10 / 15 dB |
| Wilson score interval | Uncertainty on recall | `validate/checks.py` | ✅ |
| Reliability diagram + Brier | Are probabilities honest? | `validate/checks.py` | ✅ Brier 0.05 |
| Interval coverage | Do 90% ranges cover 90%? | `validate/checks.py` | ⚠️ 0.988: intervals too wide (see section 3) |
| Null test (circular shift, 200 runs) | How often we raise alarms on pure noise | `validate/null.py` | ✅ Waits for real `fuse.run` sites |
| Backtest skill | Forecast vs flat baseline | `validate/backtest.py` | ✅ |
| Simulator recovery (planted site rank) | Does the whole chain find the planted site? | `validate/checks.py` | ✅ Waits for real sites (#169) |

---

## Decisions to make

- **D1 Fusion overlap.** U (rank mean), p_comb (CCT), `agreement` and `agreement_merged` all answer "how many signals say unusual". Proposal: **U stays only as the input to the link score L** (it needs a 0–1 per cell-day); **p_comb → p_site is the site ranking**; **show `agreement_merged`, drop the raw 0–4 badge from the dashboard.**
- **D2 CUSUM.** Fit `cusum_h` on `null` simulator runs to a target false-alarm rate (like the CCT threshold) instead of the picked 0.5; and decide whether dividing by max(φ, 1) stays (it's a quasi-likelihood adjustment not written in A1).
- **D3 Exploration.** Once the bandit merges, the bootstrap slot goes: one exploration method, not two.
- **D4 Season knapsack.** Keep only if L6 shows lower regret than weekly-only scheduling; otherwise cut.
- **D5 Unused methods.** Remove Dawid–Skene, AIS interpolation, the mixture of experts and the Knox check from the index (or build the Knox check: it's one line).
- **D6 Gi\*.** Add a test against `esda` on a small grid, or fix the docstring.
- **D7 Intervals too wide.** 0.988 coverage at a 90% target means φ is overestimated or the interval rounds outwards; P5 should check before the pitch, since too-wide intervals hide real surprises.
- **D8 GLM vs EWMA.** On slowdowns the GLM loses to EWMA (−0.12 vs +0.43). The 2 km fit (#137) may change that; if it still loses, the forecast for slowdowns should be EWMA.
