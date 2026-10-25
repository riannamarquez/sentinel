# Sentinel — demo runbook (for Rianna & Claire)

A map of what Rizhu built and exactly how to drive the demo without her. Everything here is read off the actual code (`sentinel/api/app.py`, `states.py`, `agents/`, `eval/`, and `web/app/page.tsx`).

---

## 1. The one-paragraph pitch

Fraud rules at banks fall behind the attacks they're meant to catch, and every rule change risks flagging honest customers. **Sentinel is a safe test lab for that problem.** It builds a fake bank, a **Red** agent finds a way to move stolen money past the current rules, a **Blue** agent proposes a new rule to close the gap, **deterministic code (not an AI) scores that rule on data neither agent has seen**, and **only a human can approve it**. In the demo: the current rules catch **8 of 48** unseen attacks; Blue's fix catches **32 of 48** and adds **zero** false alarms.

**The whole trust story in one line:** *AI only proposes. Code scores. A human approves.* That's the thing judges remember.

---

## 2. What you can actually open

There are **two** front-ends. Know which one you're showing.

| URL | What it is | Needs backend? |
|---|---|---|
| **`/`** (home) | The **interactive lab** — the real thing. You click through 6 steps and the FastAPI backend actually runs each one. | **Yes** (`make run`) |
| **`/demo`** | The **fraud workflow demo** — a scripted, offline replay (no backend, no API keys). 7 stages, Next/Back buttons. | No |
| **`/juice-shop`** | **Bonus:** the same red/blue loop pointed at a real vulnerable web app (OWASP Juice Shop). Offline, 7 stages. | No |

> On `rianna-demo`, `/demo` is the fraud workflow demo (exactly as the README describes it — Rizhu's page, untouched). The Juice Shop walkthrough lives on its own route at **`/juice-shop`** as a bonus; the two don't affect each other.

**My recommendation for presenting:** show the **interactive lab at `/`** as your main demo — it's backend-driven and genuinely impressive. Keep the `/demo` workflow demo as a no-backend backup, and show `/juice-shop` only if you have time and want to prove the loop generalizes.

---

## 3. Repo map (plain English)

**Backend — `sentinel/` (Python + FastAPI + SQLite):**

- `sim/` — the seeded fake bank. `world.py` builds accounts + transactions, `fraud.py`/`benign.py` generate the two kinds of behavior, `rng.py` is the seeded randomness, money is integer **cents** everywhere.
- `scenarios/factory.py` — cuts the data into **splits**: `SEARCH` + `REGRESSION` (what Blue is allowed to test on) and `FINAL_HOLDOUT` (locked away for the independent evaluator only).
- `features/registry.py` — the library of signals rules can use. Key property: **a feature can only look at the past**, never future transactions (there's a test for this).
- `detector/` — the rules engine. `baseline.py` = **BASELINE_V1 (rules R1, R2, R3)**. `score.py` runs a scenario through rules and says "alert / no alert + which rules fired." `patches.py` applies a proposed rule (like R4). `explain.py` computes *near misses* — why a rule almost fired but didn't.
- `eval/` — `evaluator.py` scores a candidate rule-set vs the baseline on the holdout; `gates.py` are the **safety gates** (e.g. false-positive budget) that must all pass.
- `agents/` — `red.py` (attacker) and `blue.py` (defender). **Both only *propose*; neither can touch the detector.** Red picks from an allow-listed set of moves; Blue proposes ≤3 patches built from the feature registry.
- `api/` — `app.py` is the FastAPI server and orchestrator; `states.py` is the explicit **state machine**; `store.py` is the SQLite **append-only audit log** + persistence.
- `llm/adapter.py` — the LLM plug (modes: `live` / `replay` / `fixture`). `fixtures.py` holds the canned Red attack and Blue fix.

**Frontend — `web/` (Next.js + React Flow):**
- `app/page.tsx` — the interactive lab (the 6-step flow). `app/demo/page.tsx` — the scripted workflow demo.
- `app/components/` — one component per step: `SetupCard`, `BaselineStep`, `RedStep` + `NetworkMap` (the attack graph), `BlueStep`, `ScorecardStep`, `ApprovalStep`, plus `EvidenceLog` (the audit trail) and `WorkflowNav`.
- `app/api.ts` — the thin client that calls the backend.

> There's also a `sentinel/juice_demo/engine.py` in the tree — a separate Juice Shop engine someone started. It's not part of the fraud lab flow.

---

## 4. The flow: Red → Blue → evaluator → human

Every round is one **run** moving through an explicit state machine (`sentinel/api/states.py`). In order:

```
GENERATE_WORLD → BASELINE_SCORE → RED_PROPOSES → VALIDATE_ACTIONS → RUN_SIMULATION
→ MEASURE_OUTCOME → BLUE_PROPOSES → VALIDATE_PATCH → EVALUATE_HOLDOUTS → APPLY_GATES
→ AWAIT_HUMAN → (APPLY_NEW_VERSION | REJECT_NO_CHANGE) → RECHALLENGE → COMPLETE
```

In words:
1. **Build the bank**, then **score the current rules** (R1–R3) so you know the baseline.
2. **Red proposes** attacks (up to 4 turns). Invalid moves are *dropped, never repaired*. A "bypass" = an attack that moved ≥ the goal **and** tripped no alarm.
3. **Blue proposes** a patch. If a real LLM is wired, Blue runs an *observe → propose → test on dev data → revise* loop (max 3 turns) — but it **only sees SEARCH + REGRESSION data, never the final holdout**.
4. **The evaluator** opens the final holdout (the data no agent saw) and scores baseline vs candidate. Then the **safety gates** run.
5. **You decide.** Approve is blocked — in the UI *and* enforced server-side (HTTP 409) — if any gate failed. Approve creates **detector v2**.
6. **Rechallenge:** a *fresh* attack (not in the test set) runs against whatever detector your decision selected. Every transition is written to the append-only audit log.

Anything that errors transitions to `FAILED` (fail-closed) — it never silently ships a rule.

---

## 5. The demo script (interactive lab at `/`)

Start both servers: `make run` (backend :8000) and `cd web && npm install && npm run dev` (frontend :3000). Open `localhost:3000`, leave **seed 7, 200 accounts**. Click through the 6 steps on the right rail. Say roughly this:

1. **Create lab** → *"We spin up a synthetic credit union — seed 7 gives 167 customers and ~9,700 transactions. Everything here is fake; no real people or money."*
2. **Baseline** → *"These are the bank's current rules, R1–R3. They catch a fast mule ring and leave a normal customer alone — but watch the slow mule chain: it waits hours at each hop, so it slips through."*
3. **Red agent** → *"Red attacks the current rules. It moves **$7,022.19** out through 3 mule accounts in 5 transfers — past its $3,000 goal, on the first try, with no alarm."* (Point at the attack graph + the "why each rule stayed silent" table.)
4. **Blue agent** → *"Red hands that evidence to Blue. Blue proposes a new rule, R4: alarm if money passes through 4+ accounts within 72 hours, each holding it under 24h and forwarding at least 40%. Blue proposes — it can't deploy."*
5. **Independent test** → *"Now deterministic code — not the AI — scores R4 on 500 normal households and 48 attacks neither agent ever saw."* Point at the scorecard: **attacks caught 8/48 → 32/48**, **false alarms 49/500 → 49/500 (zero added)**, all 5 safety gates pass.
6. **Your decision** → *"Only a human ships it. Approve creates detector v2 — and if the gates had failed, the server itself would refuse approval."* Then the **rechallenge**: *"A brand-new attack runs against v2. It's caught, and R4 is the rule that fires. The loop closed."*

Use the **Evidence log** tab to show the append-only audit trail if asked.

---

## 6. Questions judges will ask (and honest answers)

- **"Is the AI actually finding this?"** — Two honest parts. **The LLM agents are fully implemented**, not scaffolding: `sentinel/llm/adapter.py` has working Gemini, OpenAI (Chat JSON), and gateway transports with retries, call recording, and deterministic replay; `LLMRedPolicy` drives Red (with a heuristic fallback) and `blue.run_repair` is a real observe → propose → test-on-dev-data → revise loop. **But the demo runs in `fixture` mode by default** (`SENTINEL_LLM_MODE=fixture`, `SENTINEL_RED=heuristic`/`fixture`), so Red and Blue replay a fixed attack and the known-good R4 fix — deliberate, because it keeps the demo fast and deterministic. Flip `SENTINEL_LLM_MODE=live` + `SENTINEL_RED=llm` with a provider, model, and API key and the *same* loop runs against a real model. Either way, **the scoring is 100% deterministic code, never the model.** (Note: the top-level README still calls the live agents "stubs" — that line is stale relative to the adapter code; worth fixing.)
- **"How do you know the fix generalizes?"** — `make feasibility`: R4 passes the gate on **11/11 seeds**, each time 0 new false positives, 8/48 → 32/48.
- **"What does it still miss?"** — R4 misses 16/48: chains that hold money >24h, chains that are too short, or that forward <40% per hop. Honest about it.
- **"Could Red trick Blue?"** — Red's free-text rationale is deliberately **not** forwarded to Blue (see `blue.prompt_inputs`), and Blue never sees the holdout. Good answer to a sharp question.
- **Limitations to own:** no auth (anyone reaching the API can approve); the test set isn't retired after use, so the chosen fix's generalization is slightly overstated; 48 attacks / 500 households is demo-scale, not a real-world accuracy claim.

---

## 7. If something breaks at the table

- **`'next' is not recognized`** → you skipped `npm install` in `web/`. Run it once.
- **Frontend loads but steps error** → the backend isn't up. `make run` in a second terminal (needs `uv`).
- **Don't want to risk the live backend on stage** → use the workflow demo (`/demo`) — it's offline and scripted. (The Juice Shop version is at `/juice-shop` if you want it.)
