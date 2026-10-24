# Sentinel — Design Document v2

Oct 24, 2026 · revision of the Oct 23, 2026 design by @Claire

## What changed from v1

This revision keeps the v1 design and its intent. It changes only the following, which come from the [design review](design-review.md). Sections that changed are marked **(v2)**.

| Change | Where | Review finding |
|---|---|---|
| A rule is now a list of conditions combined with AND, so "new device + large transfer" can be written as one rule. Adds the `transfer_amount` feature. | §4.2, §5.2 | 1.1.1 |
| Defines one legitimate scenario and the FPR formula. | §6.2 | 1.2.1 |
| The detector only sees transactions with `timestamp <= alert time`, enforced in `detector.score()`. | §5.3 | 1.2.2 |
| Build order is now scenario factory → Red → evaluator → Blue. | §8 | 5.1 |
| One seeded RNG per component, and money stored as integer cents. | §5.1, §4 | 2.6 (minimal) |
| `pass_through_ratio` is 0 when the window has no inflow (needed to make the feature computable). | §5.2 | 1.2.4 (partial) |
| Baseline tuned so v1 flags under 15% of benign households: R1 (velocity) also requires ≥ $1,000 sent out in the same hour, and R2 (pass-through) also requires ≥ $5,000 received in the same 6 h window. Adds the `velocity_in_amount` feature. | §4.2, §5.2 | §10 feasibility |
| `short_hold_hop_count` only counts a hop that forwards ≥ 40% of what arrived. | §5.2 | §10 feasibility |
| Known limitations section for the deferred findings. | §9 | 2.1, 1.1.4, 1.2.3, 4.1/4.2 |
| Feasibility result for the demo fix. | §10 | 5.2 |

Everything else in the review is deferred for the hackathon.

---

## 1. Overview

Sentinel is a deterministic fraud-testing loop. Red finds a gap, Blue proposes a constrained rule patch, code (never an LLM) scores the patch on frozen holdouts, and a human approves it.

**Goals (P0)**

- One seeded small-bank world with synthetic normal traffic and a rules-based detector.
- One fixed mule-ring scenario plus Red-generated variants from an allowlisted move set.
- Blue rule and threshold patches, evaluated on search, regression and hidden holdout splits.
- An approval screen with hard gates, a versioned audit log, and a replay that runs with no LLM connectivity.

**Stretch:** P1 is the Builder agent, one real sponsor adapter (Nessie or CRS), advanced graph features, and agent-to-agent messaging. P2 is judge-proposed scenarios and learned detectors.

**Non-goals:** real money, real PII, live third-party systems, production alerts, autonomous deployment, unrestricted agent code execution, or claims of bank-grade accuracy.

**Design principles**

| Principle | What it means in the design |
|---|---|
| Reproducible over flashy | Every run is a pure function of (config, seed, detector version, actions). |
| Measured over narrated | All metrics come from the evaluator, with raw numerators and denominators. |
| Human-gated over autonomous | Only `POST /approvals` can create a detector version. |
| Synthetic only | All IDs are local to the test universe and labeled SYNTHETIC. |

**Hackathon gate (default, configurable):**

- The candidate's FPR increase is ≤ 0.5 percentage points on the frozen benign holdout.
- No previously caught regression scenario is lost.
- Recall improves on held-out variants.
- The rule schema is valid, and there are no unauthorized moves.

## 2. High-level design: architecture

Sentinel is one FastAPI service over pure-Python modules and a SQLite store. LLMs sit behind a single adapter and never touch metrics or versions.

Each backend owns one side of the loop, and the frontend reads only the API:

| Component | Contains | Owner |
|---|---|---|
| Frontend: Next.js + React Flow | Graph and timeline, attack/repair steps, metrics and approval, Live/Replay | Product / Frontend |
| API: FastAPI | Run state machine, SSE status events, 409 when a gate fails | Backend 2 |
| World + Red | Simulation engine (seeded world and traffic), features and detector (rule scoring, snapshots), Red agent (allowlisted moves only), scenario factory (3 frozen splits), Builder agent (P1: sentence to `BankConfig`) | Backend 1 |
| Blue + Judgment | Blue agent (constrained rule patches), evaluator and gates (frozen data, no LLM), approval and audit (human-only versioning) | Backend 2 |
| Shared infra | LLM adapter (validated and replayable), SQLite store (runs, versions, audit) | Backend 2 |

The frontend talks only to the API. Both agents call the LLM adapter, and everything else is deterministic code.

| Layer | Tech | Why |
|---|---|---|
| Frontend | Next.js, React, React Flow | Graph view out of the box; fast to build |
| API | FastAPI + SSE | Pydantic schemas shared with the agents; streaming run status |
| Engine, features, evaluator | Python, NetworkX | Deterministic; graph hop features in a few lines |
| Store | SQLite + JSON columns | Zero setup, one file to snapshot for replay |
| Agents | One LLM via a typed adapter; optional Fetch.ai uAgents wrapper later | Orchestration only after the loop works (PRD §7) |

## 3. High-level design: one round of the loop

Each run is a row in `runs` that walks a fixed state machine. Every transition writes an `AuditEvent`, which is what makes replay and the history tab possible. Nothing reaches a new detector version without passing the gates and a human decision.

States, in order:

1. Initialize lab
2. Generate world
3. Baseline score
4. Red proposes
5. Validate actions
6. Run simulation
7. Measure outcome. If there is no bypass yet, go back to Red proposes, up to 4 turns.
8. Blue proposes
9. Validate patch
10. Evaluate holdouts
11. Apply gates
12. Await human, then the Approve? decision:
    - Yes → 13. Apply new version → 15. Rechallenge
    - No → 14. Reject: no change → 15. Rechallenge
16. Complete

That is 16 states and 1 human decision. (v1 said 15.)

If no patch passes the gates, the run still reaches Await human, with the report showing "No acceptable patch" and Approve disabled. Rechallenge runs a fresh holdout scenario against whichever version is now active.

**Failure handling:** an invalid LLM output is retried twice, then the step fails closed and the run stops with its evidence kept. Invalid actions or patches are logged and dropped, never repaired silently.

## 4. Low-level design: data model **(v2)**

All schemas are Pydantic models in one shared `schemas/` package. They are exported as JSON Schema so the frontend gets matching TypeScript types. They freeze at hour 3.

**Money (v2):** every amount, balance, and money threshold is an `int` in **cents** (`amount_cents`). There are no floats for money anywhere: not in schemas, features, rules, or the store. Display code divides by 100. Ratios such as `pass_through_ratio` stay floats because they are not money.

### 4.1 Entities

| Entity | Key fields | Written by | Notes |
|---|---|---|---|
| `BankConfig` | lab_id, seed, account_count, simulation_days, customer_segments, initial_balance_range_cents, detector_version | API (create lab) / Builder | Immutable once a run starts |
| `Customer` | customer_id, segment, income_band, device_ids | Sim engine | Segments: salaried, gig, student, small business |
| `Account` | account_id, customer_id, created_at, balance_cents, risk_tags | Sim engine | Balance never below 0 |
| `Transaction` | transaction_id, from_id, to_id, amount_cents, timestamp, device_id, merchant_category?, scenario_id, ground_truth_label | Sim engine | Label hidden from Red and Blue |
| `SimulationAction` | type (open_synthetic_account, simulated_transfer, change_simulated_device, wait), timestamp_offset, source_id?, target_id?, amount_cents? | Red / fixtures | Allowlisted enum only |
| `Scenario` | scenario_id, template_id, seed, actions[], malicious_label, split (search, regression, final_holdout), owned_account_ids[] | Red / scenario factory | Exposed holdouts retire into regression. `owned_account_ids` is new in v2, see §6.2. |
| `DetectionResult` | scenario_id, detector_version, alert, triggered_rule_ids[], features{}, first_alert_time? | Detector | Feature snapshot kept for the UI |
| `RulePatch` | patch_id, base_version, operation (add, modify, disable), rule_id, all_of[] (conditions, see §4.2), rationale | Blue | feature_key and operator allowlisted in every condition |
| `EvaluationReport` | run_id, baseline_version, candidate_version, benign_n, attack_n, dataset_hashes, recall_before/after, fpr_before/after, regression_pass, holdout_pass, gate_pass, eligible_for_approval | Evaluator | Only source of metrics in the UI |
| `AuditEvent` | event_id, timestamp, actor, run_id, action, input_hash, output_hash, version_before, version_after | Every state change | Append-only |

**Storage:** SQLite with one table per entity, plus a `runs` table holding the state-machine status. Large blobs (traces, feature snapshots) are JSON columns. Detector versions are rows in `detector_versions` (version, rules_json, parent_version, created_by_event_id) and are never updated in place.

### 4.2 Rule format **(v2)**

A rule is a list of conditions combined with AND. A detector version is a list of rules, and an alert fires if **any** rule matches. So rules are OR'ed together, and conditions within a rule are AND'ed.

```
Rule      = { rule_id, all_of: [Condition, ...] }          # 1 to 3 conditions
Condition = { feature_key, operator, threshold, window_hours?, params? }
operator  ∈ { ">=", ">", "<=", "<" }
```

- `feature_key` must be in the feature registry (§5.2).
- `params` holds feature-specific parameters declared by that feature, such as `n_hours` for `new_device_before_transfer`. Unknown params are rejected.
- Money thresholds are integer cents.
- A single-condition rule is just `all_of` with one entry.

**Baseline v1, in the new format:**

```json
[
  {"rule_id": "R1", "all_of": [
    {"feature_key": "velocity_out_count", "operator": ">=", "threshold": 5, "window_hours": 1},
    {"feature_key": "velocity_out_amount", "operator": ">=", "threshold": 100000, "window_hours": 1}
  ]},
  {"rule_id": "R2", "all_of": [
    {"feature_key": "pass_through_ratio", "operator": ">=", "threshold": 0.9, "window_hours": 6},
    {"feature_key": "velocity_in_amount", "operator": ">=", "threshold": 500000, "window_hours": 6}
  ]},
  {"rule_id": "R3", "all_of": [
    {"feature_key": "new_device_before_transfer", "operator": ">=", "threshold": 1, "params": {"n_hours": 24}},
    {"feature_key": "transfer_amount", "operator": ">=", "threshold": 100000}
  ]}
]
```

R3 reads: "the outgoing transfer is made from a device first seen less than 24 hours ago, **and** it is for at least $1,000.00." In v1's format this had to be two separate rules, which would fire on every large transfer and on every transfer from a new device.

R1 reads: "at least 5 transfers went out in the last hour, **and** together they total at least $1,000.00." v1 had only the count, which fired on students splitting a group bill (several $10–$40 transfers in a few minutes).

R2 reads: "at least 90% of what came in over the last 6 hours went back out, **and** at least $5,000.00 came in during those 6 hours." v1 had only the ratio, which fired on any account that spends what it just received. In the feasibility run (§10), that was half of all benign households, mostly gig workers and small businesses. The amount condition limits R2 to mule-sized sums actually passing through. It is on the inflow, not the outflow, because a business paying payroll or suppliers from its existing balance sends large sums with little coming in.

Both changes add an AND condition rather than raising a threshold, so the original signal is unchanged and only its scope narrows.

`RulePatch` uses the same `all_of` list. Blue's validation (§6) checks every condition: the feature_key is known, the operator is allowlisted, the threshold is within the feature's bounds, `window_hours` is ≤ 168, and there are at most 3 conditions.

## 5. Low-level design: simulation, features, detectors

### 5.1 Seeded randomness **(v2)**

v1 passed one `random.Random(seed)` everywhere. That made every component's output depend on how many random numbers every other component drew first. Adding one draw to the benign generator would change Red's scenarios.

v2 gives **each component its own RNG**, derived from the lab seed and the component's name:

```python
def rng_for(seed: int, *component) -> random.Random:
    key = "|".join(str(p) for p in (seed, *component))
    return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))
```

Components and their streams:

| Component | Stream |
|---|---|
| World generator | `rng_for(seed, "world")` |
| Benign traffic | `rng_for(seed, "benign", segment, i)` per benign scenario |
| Scenario factory | `rng_for(seed, "scenarios", split, template_id, i)` per scenario |
| Fixtures / hand-written fraud | `rng_for(seed, "fraud", template_id, i)` |

Use SHA-256, not Python's `hash()`, which is randomized per process. The same config and seed always produce the same ordered event trace (US-01).

### 5.2 Simulation engine (`sim/`)

1. `generate_world(config) -> World` creates customers per segment, accounts, devices and opening balances, using the world RNG.
2. `generate_benign(world, days) -> list[Transaction]` generates hourly ticks. Each customer follows a routine template: payday every 14 or 30 days, rent on the 1st, 3–10 merchant purchases a week, and occasional family P2P. It includes the false-positive stress cases: frequent small transfers, salary/rent rhythms, and device upgrades.
3. `apply_actions(world, actions) -> list[Transaction]` validates each `SimulationAction` against the allowlist and bounds (amount_cents > 0, ≤ balance, ordered timestamps, existing accounts). It then emits transactions tagged with `scenario_id` and `ground_truth_label = malicious`.
4. Events are sorted by `(timestamp, transaction_id)` to keep ordering deterministic.

**Feature library (`features/`) (v2 signature):** each feature is a registered pure function:

```python
f(view: HistoryView, window_hours: int, params: dict) -> float
```

`view.scored` is the outgoing transaction being scored (its `from_id` is the account, and its `timestamp` is `at_time`). `view.txns` is the history the feature may read (see §5.3). The registry key is what rules and Blue may reference.

| feature_key | Measures | MVP? |
|---|---|---|
| velocity_out_count | Outgoing transfers in the window | Yes |
| velocity_out_amount | Outgoing cents in the window | Yes |
| **velocity_in_amount (v2)** | Incoming cents in the window. Needed by R2. | Yes |
| new_device_before_transfer | 1 if the scored transfer's device was first seen < `n_hours` ago, else 0. Param `n_hours`. | Yes |
| **transfer_amount (v2)** | Amount in cents of the transfer being scored. Needed by R3. | Yes |
| near_threshold_amount | Count of amounts within 10% below a reporting threshold | Yes |
| pass_through_ratio | Cents out / cents in over the window. **v2: 0 when there is no inflow in the window.** | Yes |
| min_hold_hours | Shortest time money sat before leaving | Yes |
| short_hold_hop_count | Longest chain of consecutive transfers ending at the scored one, where each transfer leaves less than 24 h after the previous one arrived **and forwards at least 40% of that amount** (the same money moving on). A time-respecting walk. Params `hold_hours` (24), `min_carry_pct` (40). | Yes, the demo fix |
| account_age_hours | Age of the account at transfer time | Stretch |

### 5.3 Detector and the no-lookahead rule **(v2)**

`detector/score(scenario, rules) -> DetectionResult` scores **online**: it walks the scenario's transactions in `(timestamp, transaction_id)` order, and for every outgoing transaction `t` from an account the scenario owns, it evaluates the rules as of `t.timestamp`. The first rule match sets `alert = true`, `first_alert_time = t.timestamp`, and records `triggered_rule_ids` and the feature snapshot.

**No lookahead. The detector may only see transactions with `timestamp <= alert time`.** This is enforced in one place, inside `detector.score()`:

- Before evaluating rules for `t`, `score()` builds a `HistoryView` with `bisect_right` on the sorted timestamps: `view.txns = txns[:bisect_right(timestamps, t.timestamp)]`. That contains every transaction with `timestamp <= t.timestamp` and nothing later.
- Features receive **only** that `HistoryView`, never the full trace, so a feature has no way to read the future. Features are not allowed to import the store or the simulation.
- **Test:** for every alerting scenario in the fixtures, cut the trace at `first_alert_time` and re-score it. The result must be identical. `scripts/feasibility.py` runs this check on every scenario.

Baseline v1 ships three rules (§4.2): velocity (≥ 5 out in 1 h), pass-through (≥ 0.9 in 6 h), and new device + large transfer. The golden mule ring trips the velocity rule. The slow variant trips none.

## 6. Low-level design: agents and evaluator

Agents only propose structured JSON. Deterministic code validates, simulates and scores everything they propose.

**LLM adapter (`llm/adapter.py`):** one function, `propose(role, prompt_inputs, response_schema) -> model`. It calls the provider, validates against the Pydantic schema, retries up to 2 times on invalid output, then fails closed. Every request and response is logged with its prompt version. A `ReplayAdapter` returns stored responses by input hash, which is how US-08 (no-LLM replay) works.

**Red agent (`agents/red.py`)**

- **Inputs:** public detector rules, allowed move types and bounds, the objective ("move ≥ $X out of the source account without an alert"), and search history (past attempts and whether they alerted).
- **Output:** up to 5 candidate `Scenario`s per turn, each ≤ 30 actions, with a rationale.
- **Loop:** validate actions → `apply_actions` → `score` on the current detector. If there was no alert and money moved, record a bypass with the feature values that stayed under each rule's threshold ("why it worked"). Cap of 4 turns per run.
- **Cannot see:** ground-truth labels on other scenarios, holdout scenarios, the evaluator.

**Blue agent (`agents/blue.py`)**

- **Inputs:** the bypass trace, current rules, the feature catalog, and diagnosis evidence (each rule's feature value vs. threshold on the bypass).
- **Output:** up to 3 `RulePatch` candidates with rationale. Patches may use multi-condition rules (§4.2).
- **Validation:** an unknown feature_key or operator in any condition, a threshold outside bounds, a window over 168 h, or more than 3 conditions → rejected before evaluation (US-06).
- **Cannot see:** holdout labels, or run any code.

**Scenario factory (`scenarios/`):** builds three splits from different seeds and template families. *Search* is what Red and Blue see. *Regression* holds every attack ever caught plus benign lookalikes. *Final holdout* is hidden variants and benign traffic from a fresh seed. When a holdout scenario is shown in the UI, it retires into regression and a new hidden seed is drawn.

### 6.1 Evaluator (`eval/evaluator.py`)

The evaluator runs baseline and candidate rules on identical frozen datasets (hashes recorded) and computes metrics at the scenario level.

### 6.2 What one scenario is, and the FPR formula **(v2)**

Benign traffic is continuous per-customer activity, so v1's "flagged legitimate scenarios / legitimate scenarios" had no countable unit. v2 defines it:

**One legitimate scenario = one benign household over a fixed 28-day window.** That is one customer, plus any dependents generated with them (for family P2P), together with all of their transactions in the window. The scenario factory generates it from `(segment template, rng_for(seed, "benign", segment, i))`.

- **Owned accounts:** the household's own accounts. Counterparties such as employer, landlord, merchants, and friends are external (`EXT-*`) and are not scored.
- **Isolation:** each scenario, benign or malicious, is scored on its own transactions only. Scenarios do not share accounts, so one scenario's alerts cannot land on another's.
- **Flagged:** a scenario is flagged if the detector raises at least one alert on any owned account during the window. A household counts once, however many alerts it gets.
- **Malicious scenarios** use the same rules. Owned accounts are the source account and every mule account the scenario uses. A malicious scenario is "caught" if any of them alerts.

Formulas, all with integer counts:

```
FPR           = flagged benign scenarios / benign scenarios
Attack recall = flagged malicious scenarios / malicious scenarios
FPR gate      : (candidate flagged benign − baseline flagged benign) × 10000
                  ≤ 50 × benign scenarios             # ≤ 0.5 percentage points
```

With 500 benign scenarios, the gate allows at most 2 newly flagged households.

The other metrics:

- Detection latency = first alert time − first malicious event, or "undefined" if there was no alert.
- Gates: FPR increase ≤ 0.5 pp, regression recall = 100% of previously caught, holdout recall improves, schema valid. `eligible_for_approval` = all gates pass. If no candidate passes, the report says "No acceptable patch."

**Builder agent (P1):** a sentence becomes a `BankConfig` → a world is generated → sanity checks run (rent 25–40% of income, ≤ 2 paydays/month for salaried, no negative balances) → failures are fed back to the LLM to revise the config, up to 3 attempts.

## 7. Low-level design: API and frontend

The API is FastAPI. Long steps return a `run_id` right away and stream status over SSE, so the UI never blocks on an LLM call.

| Endpoint | Body → returns | Owner |
|---|---|---|
| `POST /labs` | BankConfig → lab_id, world summary (accounts, txn count, edges) | Backend 1 |
| `POST /labs/{id}/baseline` | → run_id; DetectionResults for the golden fixtures | Backend 1 |
| `POST /labs/{id}/red-runs` | objective, max_turns → run_id; candidates, bypass trace, why-it-worked | Backend 1 |
| `POST /labs/{id}/patches` | bypass_id → run_id; RulePatch candidates + diagnosis | Backend 2 |
| `POST /labs/{id}/evaluations` | patch_id → EvaluationReport | Backend 2 |
| `POST /labs/{id}/approvals` | report_id, decision (approve, reject) → new detector version or unchanged; AuditEvent | Backend 2 |
| `GET /labs/{id}/timeline` | → ordered events for the graph and timeline | Backend 1 |
| `GET /labs/{id}/reports` | → all EvaluationReports + detector version history | Backend 2 |
| `GET /labs/{id}/replay` | → the full stored run for LLM-off playback | Backend 2 |
| `GET /runs/{run_id}/events` (SSE) | → state transitions + partial results | Backend 2 |

`POST /approvals` returns 409 when `eligible_for_approval` is false, so a failed gate is enforced server-side, not just greyed out in the UI.

**Frontend (Next.js + React Flow)**, a three-column layout from the PRD:

| Area | Shows | Data source |
|---|---|---|
| Left: graph + timeline | Account network, animated transfers, red path highlighted, alerts as badges; click a node to see its transactions and feature snapshot | `/timeline`, `DetectionResult.features` |
| Center: attack/repair sequence | Step cards: Create lab → Baseline → Red challenge → Blue repair (rule diff) → Independent test → Approve → Rechallenge | SSE run events |
| Right: metrics + approval | Recall and FPR before/after with n shown, latency, gate badges, Approve/Reject (disabled on failed gates), version history | EvaluationReport |
| Header | SYNTHETIC label, seed, detector version, Live/Replay toggle | Lab + replay |
| History tab | Past runs and audit log, replayable | `/reports`, `/replay` |

**UI rule:** every number on screen comes from an evaluator field. No LLM text is shown as a metric. Money is shown as `amount_cents / 100`.

## 8. Team split and build order **(v2)**

The PRD's four workstreams collapse into three. Backend 1 owns the attack side, Backend 2 owns the defense and judgment side, and Product/Frontend owns everything the judge sees. The plan assumes a 1.5-day (36-hour) hackathon with staggered sleep, and the loop must run end to end by hour 20.

| Role | Owns | Modules | Done when |
|---|---|---|---|
| **Product / Frontend** | UI, demo narrative, fixtures-driven mocks, README, pitch, recorded backup, sponsor story | `web/`, `fixtures/`, README | Judge can run the 3-minute demo end to end in Live and Replay modes |
| **Backend 1: World + Red** | Sim engine, benign traffic, feature library, detector, golden fixtures, scenario factory, Red agent, Builder (P1) | `sim/`, `features/`, `detector/`, `scenarios/`, `agents/red.py` | Same seed gives identical trace; Red finds the slow-variant bypass with why-it-worked |
| **Backend 2: Blue + Judgment** | LLM adapter + replay, evaluator, gates, Blue agent, patch validation, approval service, audit log, API/SSE, SQLite store | `llm/`, `eval/`, `agents/blue.py`, `api/`, `store/` | A passing patch can be approved into v2; a failing one returns 409; replay works offline |

### Build order (v2)

v1 had Backend 2 building the evaluator "with splits" (hours 3–10) before the scenario factory that produces the splits existed (hours 10–16). It also had Blue being built (hours 10–16) before Red's bypass trace, Blue's input, arrived (hour 16).

v2 builds the four core pieces in dependency order:

**scenario factory → Red → evaluator → Blue**

Each piece is done before the piece that consumes it, and nobody codes against an interface that does not exist yet.

### Handoffs (the contracts that let everyone work in parallel)

1. **Hour 3:** all three agree on `schemas/` (including the v2 rule format and cents) and check in three golden fixtures (caught fraud, missed fraud, legitimate lookalike) as JSON. The frontend builds against these with no backend running.
2. **Hour 8 (v2):** Backend 1 delivers the **scenario factory**: three frozen splits, plus `score()` and `apply_actions()` as Python functions. Run `scripts/feasibility.py` against the real factory output the same hour (see §10).
3. **Hour 13 (v2):** Backend 1 delivers **Red**: a real bypass trace for the slow variant, with why-it-worked.
4. **Hour 15 (v2):** Backend 2 delivers the **evaluator** with gates, built on the factory splits since hour 8 and checked against Red's real bypass scenarios.
5. **Hour 18 (v2):** Backend 2 delivers **Blue**: patches built from Red's real bypass trace, validated and scored by the evaluator. The frontend switches from fixtures to the live API.
6. **Hour 20:** the gate. The full loop runs once from the API before anyone sleeps. If it doesn't, everyone stops feature work and fixes the loop.
7. **Hour 31:** code freeze. After this, only demo fixes and recording.

### Hour by hour (v2)

| Hours | Product / Frontend | Backend 1: World + Red | Backend 2: Blue + Judgment |
|---|---|---|---|
| 0–3 | UI storyboard, metric definitions, golden fixtures | Schemas (shared), per-component seeded RNG, world generator skeleton | Schemas (shared), repo, FastAPI + SQLite skeleton |
| 3–8 | Three-column layout on fixtures, React Flow graph | Benign traffic, feature library, detector with `HistoryView`, baseline rules, mule ring, **scenario factory** → hand off at **H8** | LLM adapter + replay, approval + audit, SSE (none of these depend on Backend 1) |
| 8–13 | Step cards, rule-diff view, metrics panel | **Red** agent loop, why-it-worked report → hand off at **H13** | **Evaluator** with splits and gates, on the real factory splits |
| 13–18 | Wire to live API | False-positive stress scenarios, Red polish, support Blue integration | Evaluator checked on Red's bypasses → **H15**. **Blue** agent and patch validation on the real bypass trace → **H18** |
| 18–20 | Integration | Integration | Integration: end-to-end run. **Gate** |
| 20–26 | Staggered sleep (~4 h each); awake person: graph animation, gate badges, history tab | Staggered sleep; awake: edge-case tests | Staggered sleep; awake: regression tests, deterministic replay check |
| 26–31 | Pitch, README, sponsor narrative | Builder agent (P1) only if the gate passed | Sponsor adapter (Nessie/CRS) only if real and stable |
| 31–36 | Record backup video, rehearse the 3-minute demo twice, submit | Pre-run seeded rounds, freeze | Lock replay trace, freeze |

**Still open:** which LLM provider, and whether one sponsor API can be shown live. Holdout sizes are now set by §10: 500 benign scenarios, and about 50 attack scenarios.

## 9. Known limitations (deferred for the hackathon)

- **Approval race:** two reports built on the same base version can both be approved, and the second silently drops the first one's rules (review 2.1).
- **Holdout is not truly frozen:** it changes when a scenario is "shown in the UI", which the server cannot observe, so a report can refer to a holdout that has since changed (review 1.1.4).
- **Selection on the holdout:** all of Blue's candidates are scored on the final holdout and the passing one is kept, which overstates how well the chosen patch generalizes (review 1.2.3).
- **No authentication and Red → Blue prompt injection:** anyone who can reach `POST /approvals` can approve, and Red's free-text rationale can reach Blue's prompt (review 4.1, 4.2).
- **Opening-balance funding evades pass-through:** `pass_through_ratio` is 0 when nothing came in during the window, so an account that sends money it already held (for example, its opening balance) never trips R2.
- **Low-carry hops evade the hop-count fix:** fraud that forwards less than 40% of what arrived at each hop (for example, by splitting it many ways) does not extend a `short_hold_hop_count` chain.

## 10. Feasibility of the demo fix (no LLM)

`scripts/feasibility.py` checks the riskiest assumption in the demo (review 5.2): that a `short_hold_hop_count` rule catches the slow mule variants without exceeding the FPR budget. It uses only the standard library and no LLM.

- **Data:** 500 seeded benign households across the four segments, including households where a parent forwards an allowance on payday and a dependent relays part of it to a sibling. Also 48 hand-written hop-chain fraud scenarios (6 templates × 8 seeded copies).
- **Rules:** baseline v1 (§4.2, with the tuned R1 and R2), and v1 plus `R4 = short_hold_hop_count >= 4` (window 72 h, each hold < 24 h, each hop forwards ≥ 40%).

Results on all 11 seeds (also in [feasibility-results.md](feasibility-results.md)):

| Seed | v1 benign flagged | Fix new FPs | Budget | Fraud caught (v1 → v1 + R4) | Gate |
|---|---|---|---|---|---|
| 7 | 61/500 (12.2%) | 0 | 2 | 8/48 → 32/48 | PASS |
| 1000 | 59/500 (11.8%) | 0 | 2 | 8/48 → 32/48 | PASS |
| 1001 | 51/500 (10.2%) | 0 | 2 | 8/48 → 32/48 | PASS |
| 1002 | 64/500 (12.8%) | 0 | 2 | 8/48 → 32/48 | PASS |
| 1003 | 56/500 (11.2%) | 0 | 2 | 8/48 → 32/48 | PASS |
| 1004 | 52/500 (10.4%) | 0 | 2 | 8/48 → 32/48 | PASS |
| 1005 | 61/500 (12.2%) | 0 | 2 | 8/48 → 32/48 | PASS |
| 1006 | 56/500 (11.2%) | 0 | 2 | 8/48 → 32/48 | PASS |
| 1007 | 47/500 (9.4%) | 0 | 2 | 8/48 → 32/48 | PASS |
| 1008 | 55/500 (11.0%) | 0 | 2 | 8/48 → 32/48 | PASS |
| 1009 | 54/500 (10.8%) | 0 | 2 | 8/48 → 32/48 | PASS |

The fix passes every gate on all 11 seeds. R4 flags no benign household on any seed: the 40% carry rule breaks the payday → allowance → sibling chains that caused 0–3 false positives per seed before. R4 misses the two templates it was expected to miss: a chain where one mule holds the money for more than 24 h, and a chain with a single mule. Dropping to k = 3 also passes on seed 7, at 48/48.

Caveats:

- **Baseline:** v1 now flags 9.4–12.8% of benign households (it was 57% before tuning), and all of them are small businesses: R1 on payroll runs to 5 or more employees, and R3 on large payments made from a new device. R2 flags no benign household, and in this data it catches no fraud that R1 does not also catch. The golden fast ring is still caught by R1, and the slow variants still get past the baseline, so the demo story holds.
- **The recall is by construction:** the fraud scenarios are hand-written, so recall reflects the templates chosen. The meaningful output is the FPR side, which depends on how realistic the benign generator is.
