<!-- Learning layer blueprint, rev 2, 28 Nov 2026 (rev 2: regret-weighted votes, time-expanded scheduling, regret attention, review decisions R1-R5). Evidence: reports/Neural bandit patrol scheduling.md (research notes cite every source). -->

# Learning layer: per-signal agents → stack → bandit → routes

**Purpose:** turn the statistical signals NarcoPolo already computes into a patrol policy that **learns from every patrol**, while every number a human sees still traces back to an interpretable statistic.

**One-line architecture:**

```
signals (P5, P6)  →  per-signal agents, each backtested (P1)  →  combined p + agreement (P6)
      →  stack / challenger model (P1 fits on the simulator, P6 applies)  →  site value p_site
      →  Thompson-sampling bandit (P7)  →  sampled node weights  →  ship + aircraft routes (P7)
      →  simulated patrol outcomes (P1)  →  bandit update  →  evaluation (P1)
```

**Who builds what (Saturday):**

| Part | Owner | Folder | Est. |
| --- | --- | --- | --- |
| L1 Simulator drop regimes + patrol outcomes | P1 | `sim/` | 2–3 h |
| L2 Per-signal agents and their backtests | P1 | `validate/` | 2–3 h |
| L3 Combined p-value + diversity-weighted agreement | P6 | `fuse/` | 1–2 h |
| L4 Stack and challenger: fitted offline, applied in fuse | P1 fits, P6 applies, P5 pairs on the challenger | `validate/`, `fuse/` | 3–5 h |
| L5 Bandit + sample-then-route | P7 | `patrol/` | 2–3 h |
| L6 Policy evaluation + report + dashboard panel | P1 (eval), P7 (panel) | `validate/`, `dashboard/` | 3–4 h |

**Hard rule for the team:** P2, P3 and P4 stay on the real-data path (downloaders → reference/coverage → detection). Nothing here may take them off it.

---

## Design principles for this layer

1. **Statistics are the signals; learning only combines and schedules them.** No model reads raw counts, radar pixels or AIS tracks directly.
2. **A learned piece ships only if it wins.** Each rung of the ladder (L4) must beat the rung below on held-out simulator regimes, at the same patrol budget, over at least `learn.n_seeds` seeds. Otherwise the lower rung is used. The decision and the numbers go in `DECISIONS.md`.
3. **Unvisited is not zero.** A site nobody patrolled gives no reward and no update (Design principle 4). Never feed it in as "found nothing".
4. **Real labels are for checking, never for fitting.** With a handful of real events, every fit uses simulator labels; real events are reported descriptively (principle 6 still holds: every fit takes a `core.Split`).
5. **Areas, never people.** All scores are per sea cell or site. No vessel identity enters any feature, label or output (principle 10). This is also the system's EU AI Act position: it scores locations, not natural persons.
6. **Humans choose.** The dashboard shows the plan, the evidence per stop and the explore/exploit reason; a human approves or overrides. Overrides are logged.

---

## L1 Simulator: drop regimes and patrol outcomes (P1)

**Purpose:** give the learning layer labels, variety and a way to score policies.

### Steps: drop regimes

1. `sim.simulate(config, seed, regime=...)` accepts a regime name from `learn.regimes`. Each regime changes only how drops are planted:
   - `fixed`: today's single planted site, drops at a constant weekly rate
   - `two_sites`: two sites, one active in the first half of the season, one in the second
   - `pass_aware`: drops timed to avoid Sentinel-1 passes (the adversary knows the public schedule); drop times drawn from the gaps between passes
   - `displacing`: after a patrol visits the active site, the next drops move to a neighbour within `learn.displace_km`
   - `null`: no drops (calibration runs)
2. Regimes are split into **train** (`fixed`, `two_sites`) and **held-out** (`pass_aware`, `displacing`) in config; `null` is only for calibration.
3. `truth.parquet` gains `regime` and, per drop, `site_id`, `time_utc`, `active` (bool).

### Steps: patrol outcomes

`sim.patrol_outcome(truth, plan, week) -> DataFrame[site_id, asset, visited, found]`:

- `visited`: the stop is in the plan for that week
- `found`: a drop happened at that site within `learn.find_window_h` of the visit, thinned by `learn.p_find_ship` or `learn.p_find_aircraft` (a visit can miss activity)
- Unvisited sites get no row (principle 3)

### Tests (done when)

- `null` regime: no drop rows in truth; every other file still validates
- `pass_aware`: no drop is within `learn.pass_buffer_h` of a pass
- `displacing`: the next drop after a visit is at a neighbour site
- `patrol_outcome` never returns a row for an unvisited site; same seed, same outcomes

---

## L2 Per-signal agents and backtests (P1)

**Purpose:** treat each statistical property as its own "agent", score it alone, and measure how much the agents overlap, so the combination step knows which votes are really independent.

**Agents (one score per site-week, higher = more unusual):**

| Agent | Signal | Already computed by |
| --- | --- | --- |
| `oe` | log y = log((C + 0.5) / (μ + 0.5)) | P6 `fuse/cells.y` |
| `midp` | −log10 mid-p, with the BH flag | P6 detectors |
| `gi` | Getis-Ord Gi* z (weekly) | P6 detectors |
| `cusum` | Poisson CUSUM statistic | P6 detectors |
| `link` | slowdown → small-boat lag-link score S | P6 `fuse/sites.S` |

### Steps

1. `validate.signals.backtest_agent(name, regime, seeds) -> DataFrame` walks forward week by week with `core.split.folds`; at each cutoff it ranks sites by the agent alone and records: precision@k (k = `learn.alert_budget`), recall of planted sites, weeks to detection, false alerts per week (from `null` runs).
2. `validate.signals.overlap(seeds) -> DataFrame`: pairwise Cohen's κ between agents' top-k flags and Spearman ρ between their scores, on simulator output.
3. **Merge rule:** agents with κ ≥ `learn.merge_kappa` are merged into one agent (keep the one with better held-out precision@k). Expect `oe`, `midp` and `cusum` to merge: all three are driven by the same C and μ.
4. Output: `reports/signals.json` with one block per agent (the metrics above), the κ matrix, the merged agent list, and **`null`: {agent: sorted site-level scores from `null`-regime runs}** (at most 10,000 per agent). fuse turns any agent score into a site-level p as (1 + #null ≥ score) ÷ (1 + n). Today only `link` (= `p_perm`) has a site-level p.

### Tests

- On `fixed`, every agent ranks the planted site in its top k at least once
- κ of an agent with itself is 1; merged list is a partition of the agents
- No agent's walk-forward ever reads a row after its cutoff (assert on dates)

---

## L3 Combined p-value and agreement (P6)

**Purpose:** one calibrated "how unusual" number per site that does not double-count overlapping agents.

### Steps

1. For each merged agent, a one-sided p-value per site-week (from its own null distribution on `null` runs; `midp` already is one).
2. **Cauchy combination test (CCT):** T = Σ wᵢ · tan((0.5 − pᵢ)π) with **regret-based weights** (below; equal weights 1/m only until they exist); p_comb = 0.5 − arctan(T)/π. Valid in the tail under arbitrary correlation (Liu & Xie 2020), but **anti-conservative by 10–25% at α = 0.05 under positive correlation**, so:
3. **Calibrate** on `null` runs: shift the threshold until the false-alert rate per week matches `learn.target_false_alerts`.
4. Benjamini–Hochberg across sites at `q` (existing config) → `comb_flag`.
4a. **Regret-based group weights (rev 2).** Signals are not assumed equally useful. L6 writes `reports/attention.json` with, per merged group g, Δregret_g = (season regret with g removed) − (regret with all groups), averaged over **train** regimes and seeds. Weights: w_g = max(exp(Δregret_g / τ), floor) normalised to sum to 1, τ = `learn.attention_tau`, floor = `learn.attention_floor`; within a group, split equally over its agents present for the site. A group whose removal *lowers* regret gets only the floor. CCT stays valid because the weights are fixed from simulator backtests before they are applied, never fitted on the data they score. Until `attention.json` exists: equal weights, logged.
5. **Diversity-weighted agreement:** count of merged agents flagging the site (replaces the raw 0–4 count for display; the old `agreement` column stays for compatibility).

### Outputs (contract change via P1)

`fuse/sites` gains: `p_comb` (0–1), `comb_flag` (bool), `agreement_merged` (int ≥ 0).

### Tests

- On `null` runs, calibrated false alerts per week within tolerance of `learn.target_false_alerts`
- p_comb is monotone: lowering any agent's p never raises p_comb
- With identical inputs p₁ = … = p_m = p, p_comb = p (CCT reproduces a single test)

---

## L4 Stack and challenger ladder (P1 fits, P6 applies, P5 pairs)

**Purpose:** learn how much to trust each agent, and when. Each rung must beat the rung below to be used.

### The ladder

| Rung | Model | Parameters | Interpretable as |
| --- | --- | --- | --- |
| 0 | p_comb + BH (L3) | 0 learned | "the statistics alone" |
| 1 | **Stack:** logistic regression on merged-agent scores, **non-negative, monotone** weights | m + 1 (≈ 4) | "weight of each signal" |
| 2 | **Challenger A:** Neural Additive Model (NAM), one small net per agent score, summed | ≈ 1–3k, plotted as m shape curves | "how each signal's strength turns into risk" |
| 2′ | **Challenger B:** LightGBM, depth 2, monotone constraints | small; explained with SHAP | same, as a baseline for the NAM |
| 3 | **Mixture of experts:** the agents are the experts; a softmax gate over context (sea state, hours since last radar pass, AIS density, ISO week) sets how much to trust each | ≈ 20–30 | "which signal to trust in which conditions" (the scheduling part) |

### Steps: fitting (P1, offline, `validate/train.py`)

1. Training data: simulator `train` regimes × `learn.n_seeds` seeds. Rows = site-weeks, features = merged-agent scores (+ context for rung 3), label = an active drop at that site that week.
2. **Two-level time split, no leakage:** level 1 produces each agent's out-of-time scores (L2 walk-forward); level 2 fits the stack/challenger on a **later** split with `split.embargo_days`. Do not use scikit-learn `StackingClassifier` with walk-forward folds (it assumes every row is in exactly one test fold); `cv="prefit"` overfits.
3. Effective sample size n_eff = min(n, 5 × n_positive). If n_eff < 500, stop at rung 1 (Phillips et al. super-learner guidance).
4. **Promotion rule:** a rung replaces the one below only if, on the **held-out regimes**, mean precision@k improves by more than 2 × its standard error across seeds **and** calibration (Brier) does not get worse. Record the result in `DECISIONS.md`.
5. **Ablation:** refit the winning rung with each agent removed; if removing one agent changes nothing, say so in the report (the model may be re-learning Gi* or CUSUM).
6. Output: `<data root>/models/site_model.json` (agreed with P6, #160):
   - `rung` (0–3), `features` (agent names; each feature's value is −log10 of that agent's site-level p), `weights` (all ≥ 0 for rung 1), `intercept`
   - `config_hash` = `core.config.load(CONFIG_PATH)[1]` (SHA-256 of the whole config.yaml)
   - `metrics`, `seeds`, `regimes`
   - optional `p_comb_threshold`: computed here with `fuse.combine.calibrate()` on `null`-regime runs (L1); until it exists, `comb_flag` is plain BH
   - neural rungs also write `site_model.pt` (state dict only). **fuse applies rungs 0 and 1 only;** if a higher rung is promoted, open a module:P6 issue to load and run it.

### Steps: applying (P6, `fuse/learn.py`)

`fuse.learn.site_value(sites, model) -> Series p_site` in 0–1. If `models/site_model.json` is missing or its config hash is stale, fall back to rung 0 (p_site = 1 − p_comb, ranked) and log it.

### Outputs (contract change via P1)

`fuse/sites` gains `p_site` (0–1) and `model_rung` (int 0–3).

### Tests

- Rung 1 weights are all ≥ 0; increasing any agent score never lowers p_site (monotone)
- Leakage test: shuffling labels after the cutoff does not change the fitted model
- On `fixed`, the planted site's p_site ranks in the top k
- Missing or stale model → rung 0, never a crash

---

## L5 Bandit and scheduling (P7)

**Purpose:** choose which sites to visit each week so patrols both use what the model believes and keep learning where it is unsure.

### Steps

1. **Arms:** the top `patrol.top_sites` sites by p_site (existing key, 15).
2. **Posterior per site:** Beta(α, β), warm-started from the model: α₀ = n₀ · p_site, β₀ = n₀ · (1 − p_site), with n₀ = `learn.prior_strength` ("virtual visits"). New sites start from their prior; sites that drop out of the top 15 keep their state in `patrol/bandit_state.json`.
3. **Weekly update:** only visited sites update: found → α += 1; visited and not found → β += 1. Unvisited: no change (principle 3). θ therefore estimates "chance a visit finds something", which already includes the asset's miss rate; `learn.p_find_*` lives only in the simulator.
4. **Discounting:** before each week's update, α ← γα, β ← γβ with γ = `learn.discount` (drop sites move; old evidence fades).
5. **Sample-then-route (combinatorial Thompson sampling), within one week:** draw θ_s ~ Beta(α_s, β_s) for every arm; pass θ as node weights to the existing ship planner (orienteering, 24 h) and aircraft planner (4 h) in place of S. With ~15 nodes, solve the ship route **exactly** (the method's guarantee needs an exact oracle; greedy + 2-opt is the fallback above `learn.exact_max_nodes`).
6. **Explanation per stop:** `reason` = "exploit" if the site is in the top routes under posterior means, else "explore", plus the site's evidence line (existing `reasons`).

### Steps: scheduling over time (rev 2)

Routing one week at a time ignores *when* to go and *how* the season's hours are spread. Two layers, replanned every week (rolling horizon):

7. **Week layer: time-expanded orienteering.** Nodes are (site, day) for the next 7 days, one visit per site per week. Value of visiting site s on day d: v_sd = θ_s × g_sd, where g_sd is the share of the week's drop chance that falls on day d *and* is not covered by a satellite pass (from `coverage/exposure` pass times and the regime-free drop cadence; uniform if unknown). The `pass_aware` adversary drops in pass gaps, so days without passes are worth more. Solve exactly by DP over (day, subset of visited sites) when sites ≤ `learn.exact_max_nodes` and days ≤ `learn.day_slots`, else greedy by v_sd ÷ extra hours, then 2-opt per day. Each stop gets `day`.
8. **Season layer: hours as a knapsack.** Split the remaining season hours across the next `learn.horizon_weeks` weeks in proportion to each week's expected value under the posterior *plus* an uncertainty bonus (posterior standard deviation summed over the top sites), never below `learn.min_week_share` of the weekly budget and never above the weekly budget. Weeks where the bandit is unsure get more hours; that is bandits-with-knapsacks done by a simple rule, not a solver.
9. **Exploration by expected regret (rev 2).** The explore stop is the site with the highest expected regret of skipping it, E[max(θ_s − θ*_route, 0)] estimated from `learn.n_regret_samples` posterior draws (θ*_route = the lowest-value stop on the exploit route): visit what you would most regret missing, not a random draw. A light form of information-directed sampling.

### Outputs (contract change via P1)

- `patrol/plan.json` stops gain `theta` (float), `reason` ("exploit" | "explore") and, from rev 2, `day` (0–6, day of the planning week)
- `patrol/bandit_state.json`: `{site_id: {alpha, beta, last_visit_week}}`, stamped like other JSON stage files

### Tests

- Same seed + same state → same plan
- An unvisited site's α and β are unchanged after the update (apart from discounting)
- With n₀ → ∞ the plan equals the plan routed on p_site (pure exploit)
- Exact and greedy planners agree on small cases

---

## L6 Policy evaluation, regret attention and dashboard (P1 eval, P7 panel)

**Purpose:** show, on the simulator, that the learning patrol finds drops sooner than a fixed ranking, and be honest where it does not.

### Policies compared (same route planners, same budgets)

| Policy | Node weights |
| --- | --- |
| Fixed: S | today's site score S |
| Fixed: p_site | rung chosen in L4, no learning |
| Bandit | Thompson samples (L5) |
| Oracle | true drop rates (upper bound) |
| Random | random top-15 order (lower bound) |

### Steps

1. `validate.policy.evaluate(policy, regime, seeds) -> DataFrame` runs the season week by week: fuse.run on data up to the week's cutoff → policy weights → routes → `sim.patrol_outcome` → bandit update.
2. Metrics per policy and regime: **cumulative regret** vs the oracle, **weeks to first find**, **finds per patrol-hour**, and **coverage entropy** of visits (how spread out patrols are; guards against runaway feedback loops where patrols keep returning to the same place).
3. Report mean and spread across `learn.n_seeds`, train vs **held-out** regimes separately.
4. Output block `policy` in `reports/validation.json`.
5. Dashboard panel (P7): regret curves per policy, weeks-to-first-find bars, and the explore/exploit badge per plan stop.

### Steps: regret attention (rev 2)

6. **Signal attention:** rerun each train-regime season with one merged group removed; Δregret_g as in L3 step 4a. Write `reports/attention.json` = {"groups": {group: {delta_regret_mean, delta_regret_sd, weight}}, "config_hash", τ, floor, seeds, regimes}; a group's key is its agents joined with "+" in `merged` order (e.g. `oe+midp`). fuse (`combine.weights`) reads only `groups.*.weight` and `config_hash`; a stale hash means equal votes. This is what fuse uses as CCT weights, and the pitch table of "which signals earn their place".
7. **Where regret comes from:** split each policy's regret by week and by cause: *wrong site* (the oracle's site was not visited that week), *wrong day* (visited, but outside the drop's find window), *no hours* (the week's budget ran out before the oracle's site). Report the shares per policy and regime.
8. Fast mode: `make validate` uses `learn.n_seeds_quick` seeds; the full `learn.n_seeds` only for the final report.

### Tests

- Oracle regret is 0; random is worst on `fixed`
- On `null`, no policy finds anything (finds = 0) and regret is 0
- Results identical for the same seed

---

## Parameters (config, `learn:` block)

All values not given by a source are `TODO(P1)` until tuned on **train** regimes only.

```yaml
learn:
  regimes: {train: [fixed, two_sites], held_out: [pass_aware, displacing]}
  n_seeds: 20                 # TODO(P1)
  displace_km: 6              # TODO(P1)
  pass_buffer_h: 6            # TODO(P1)
  find_window_h: 24           # TODO(P1)
  p_find_ship: 0.8            # TODO(P1)
  p_find_aircraft: 0.5        # TODO(P1)
  alert_budget: 15            # = patrol.top_sites
  merge_kappa: 0.7            # TODO(P1)
  target_false_alerts: 1.0    # per week, TODO(P1)
  prior_strength: 5           # n0 virtual visits, TODO(P1)
  discount: 0.9               # per week, TODO(P1)
  exact_max_nodes: 16         # TODO(P1)
  # rev 2
  attention_tau: 1.0          # TODO(P1): softness of regret-based CCT weights
  attention_floor: 0.05       # TODO(P1): minimum weight per merged group
  horizon_weeks: 4            # TODO(P1): season-layer look-ahead
  day_slots: 7                # days in the week layer
  min_week_share: 0.5         # TODO(P1): least share of the weekly budget any week gets
  n_regret_samples: 200       # TODO(P1): posterior draws for expected-regret exploration
  n_seeds_quick: 3            # make validate; n_seeds only for the final report
```

## Review decisions (rev 2, 28 Nov 01:30)

- **R1 `site_id` = `cell_id` everywhere** (rule A2), in the simulator's stand-in `fuse/sites`, truth and outcomes.
- **R2 `week` in `sim.patrol_outcome(truth, plan, week)` is the week's start timestamp (UTC);** stops outside [week, week + 7 days) are ignored. The bandit keeps an integer week number for `last_visit_week`.
- **R3 Model features are raw agent scores** per site (= its cell): `oe` = log y, `midp` = −log10 mid-p, `gi` = weekly Gi* z, `cusum` = Poisson CUSUM statistic, named as in `learn.agents`. Trainer and fuse compute them the same way; fuse reads them from `fuse/cells`. `link` is not a model feature (site-level only); it enters through p_comb.
- **R4 `weights` in `site_model.json` is a list in `features` order** (rung 1). Higher rungs store their own parameters under `params`.
- **R5 `make validate` uses `learn.n_seeds_quick` seeds;** `learn.n_seeds` only for the final report.

## Resolved ambiguities

- **Why not a neural bandit (NeuralUCB/NeuralTS) at the top?** They were tested on 1,000–15,000 rounds; a season gives under 100 labelled visits. The NN's place is rung 2–3 of the site model, feeding the bandit's prior. If more rounds ever exist, NeuralLinear (a net with exact Bayesian last layer) is the neural bandit to try first.
- **Why CCT and not Fisher or Stouffer?** Those assume independent p-values; `oe`, `midp` and `cusum` are not independent.
- **Why fit only on the simulator?** Real labels are a handful and biased by where patrols went. They are shown, never fitted.
- **Off-policy evaluation on real patrol logs?** Not valid: the replay method needs logs from uniformly random patrols.

## Warnings

1. **Feedback loops:** a learner that only sees where it patrols can confirm itself forever. Coverage entropy and the explore badge are mandatory, not decoration.
2. **Simulator overfit:** a model that wins only on train regimes is not promoted. Held-out regimes decide.
3. **Double counting:** never show "4 of 4 detectors agree" when three of them are one signal; show `agreement_merged`.
4. **Small boats are often invisible:** Sentinel-1 misses most vessels under 15 m (Paolo et al. 2024). The pitch must say what the system cannot see.
5. **Language:** "unusual", "worth checking", "consistent with a drop-off". Never "smuggling detected".

## EU AI Act position (for the pitch; not legal advice)

- **Say:** "scores sea areas, never people"; "every flag shows the statistics behind it"; "designed for human oversight: a person approves every patrol (Art. 14)"; "learned parts are small, monotone and only used when they beat the statistics".
- **Avoid:** "AI Act compliant", "exempt because it's defence", "not a black box" on its own (the whole system is assessed, not its inputs).
- Context: the Commission's draft high-risk guidelines (May 2026) place location and area analysis outside the law-enforcement high-risk uses; the Digital Omnibus moved Annex III obligations to 2 Dec 2027. Check the final guidelines before quoting.

## Pseudo-codebase (new or changed public functions)

```
sim/       simulate(config, seed, regime="fixed")             # L1
           patrol_outcome(truth, plan, week) -> DataFrame      # L1
validate/  signals.backtest_agent(name, regime, seeds)        # L2
           signals.overlap(seeds) -> DataFrame                 # L2
           train.fit_site_model(regimes, seeds) -> dict        # L4, writes models/site_model.json
           policy.evaluate(policy, regime, seeds) -> DataFrame # L6
fuse/      combine.cct(pvalues, weights) -> Series             # L3
           combine.calibrate(null_runs, target) -> float       # L3
           learn.site_value(sites, model) -> Series            # L4
patrol/    bandit.prior(sites, n0) -> state                    # L5
           bandit.update(state, outcomes, discount) -> state   # L5
           bandit.sample(state, seed) -> Series                # L5
dashboard/ policy panel                                         # L6
```

## Build order (Saturday)

1. **Morning, in parallel:** L1 and L2 (P1); L5 on today's S as node weights (P7). By lunch: a "bandit vs fixed ranking" chart on `fixed`.
2. **Afternoon:** L3 (P6); L4 rungs 1 then 2 (P1 fits, P6 applies, P5 pairs on the NAM); L6 across all regimes.
3. **Evening:** promotion decisions in `DECISIONS.md`; dashboard panel; pitch slides built on the L6 numbers.

Contract changes (new columns in `fuse/sites`, plan stop fields, `bandit_state.json`, `models/`) go through one P1 PR before L3–L5 merge.
