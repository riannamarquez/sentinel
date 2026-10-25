# Sentinel

Fraud rules at banks fall behind the attacks they're meant to catch, and every change to a rule risks flagging honest customers. Sentinel is a safe test lab for that problem. It builds a fake bank with synthetic customers, then a **Red** agent looks for a way to move stolen money past the current fraud rules. A **Blue** agent proposes a rule to close the gap, and **deterministic code**, not an AI, tests that rule on data neither agent has seen. Only a **human** can approve the change. In the demo round, the current rules catch 8 of 48 unseen mule attacks. Blue's fix catches 32 of 48 and flags no additional normal customers.

## Run it

You need [uv](https://docs.astral.sh/uv/) (Python 3.12+) and Node.js.

```bash
# Terminal 1: backend API on http://127.0.0.1:8000
make run

# Terminal 2: frontend on http://localhost:3000 (proxies /api to the backend)
cd web && npm install && npm run dev
```

Open http://localhost:3000 and leave the default seed (7).

Other targets: `make test` runs the backend tests, and `make feasibility` re-runs the offline check behind the numbers below.

### Three ways to run the backend

| Command | Red | Blue | Needs |
|---|---|---|---|
| `make run` | heuristic (no LLM) | fixed R4 patch from `fixtures/` | nothing; the safe fallback demo |
| `make run-live` | LLM (Gemini), heuristic if a turn fails | LLM (Gemini) | `.env` with a model ID and key |
| `make run-replay` | replays the recorded LLM answers | replays the recorded LLM answers | `.env` and a recording from `run-live` |

`run-live` and `run-replay` load `.env` (`cp .env.example .env`, then fill in `SENTINEL_LLM_MODEL` and `GEMINI_API_KEY`) and refuse to start while it still has placeholders. `.env` is gitignored. Both read and write LLM responses in `data/demo.llm.db`, and both start from an empty lab database so the first round after start-up gets the IDs the recording was made with. Replay only matches that first round, so restart `make run-replay` before replaying again. In replay, a missing recording makes Red fall back to the heuristic (logged and labelled) and makes Blue fail closed.

**Seeing what ran.** The UI labels the Red panel "Red: LLM", "Red: heuristic fallback" (with the turns and reasons) or "Red: heuristic", and the Blue card "Blue: LLM live", "Blue: LLM replay" or "Blue: fixture". The same information is in the API responses (`turn_sources` on a Red run, `source` on Blue's proposals), in the evidence log's actor column (for example `agent:red:heuristic_fallback:llm_error`), and in `GET /healthz` (`red_policy`, `blue_source`, `llm_model`). Red fallbacks are also logged by the server.

**Pre-demo check.** With a server running, `uv run python scripts/demo_check.py` plays the frontend's round on seed 7. It prints each Red turn's policy and recipes, Blue's source and exact rule, the scorecard, the five safety checks and both timings. It ends with PASS, or WARN if a Red turn fell back, Blue wasn't the LLM, a safety check failed, or either step took over 60 s.

## The demo, step by step

1. **Create a fake bank.** This generates a seeded synthetic credit union. Seed 7 with 200 accounts gives 167 customers and 9,691 transactions.
2. **Test the current rules.** Detector v1 has three rules: R1 for many fast transfers out, R2 for money passed straight through, and R3 for a new device followed by a large transfer. It catches the fast mule ring and leaves the normal customer alone. It misses the slow mule chain, which waits hours at every hop.
3. **Red challenge.** With `make run`, Red's first attempt (2 mule accounts, 1-hour holds) is caught by R2. On its second turn Red holds the money 7 hours at every hop, longer than R2's 6-hour window, and moves **$6,859.00** out through 2 mule accounts in 3 transfers, beating its $3,000 goal with no alarm. With `make run-live`, the LLM chooses Red's attacks, so the turns and amounts vary. The page shows Red's plan and a table of why each rule stayed silent: every rule needs all of its checks to fire, and the attack keeps at least one check below its limit.
4. **Blue's fix.** Blue proposes a new rule, R4, in plain English: *"Alarm if money passes through 4+ accounts in a row within 72 hours, each holding it under 24 hours and forwarding at least 40%."*
5. **Independent test.** The fix is scored on a held-out set of 500 normal households and 48 attacks that neither agent saw:

   |                                  | Current rules (v1) | With R4 (v2)  |
   |----------------------------------|--------------------|---------------|
   | Attacks caught                   | 8 / 48 (17%)       | 32 / 48 (67%) |
   | Normal customers wrongly flagged | 49 / 500 (9.8%)    | 49 / 500 (9.8%) |

   All five safety checks pass. The fix adds 0 false positives against a budget of 2, the 8 attacks v1 already caught are still caught, and lookalike normal customers go from 0 flagged to 0.
6. **Human decision.** Approve or Reject. Approve is disabled if any safety check fails, and the server refuses it too (HTTP 409). Approving creates **detector v2**.
7. **Rechallenge.** A fresh slow-chain attack that wasn't in the test set runs against the now-active detector. v2 catches it, and R4 is the rule that fires.

These are the real outputs of a full round through the API with seed 7 and `make run`.

## Architecture

- **Backend (`sentinel/`, Python + FastAPI + SQLite):** a seeded simulator (`sim/`, `scenarios/`), a feature library that can only see the past (`features/`), a rules detector (`detector/`), and an evaluator with the safety gates (`eval/`). The API (`api/`) runs each round through an explicit state machine and records every step in an append-only audit log.
- **Agents (`sentinel/agents/`):** Red proposes attacks only from an allowlisted set of moves. Blue proposes at most 3 patches built from the feature registry. Both are validated before anything runs.
- **Frontend (`web/`, Next.js + React Flow):** three columns. The left shows Red's attack path as a graph. The center has the step cards. The right pins the scorecard and the approve/reject panel.
- **Determinism:** one seeded random generator per component and money as integer cents. Tests check that the same seed gives the same trace across processes and that no feature can see future transactions.

## Safety and honesty

- **Synthetic data only.** No real people, accounts or money. The UI carries a "SYNTHETIC DATA" label throughout.
- **AI only proposes.** Red and Blue can suggest attacks and rule changes. Neither can change the detector.
- **Deterministic code scores.** Every number on the scorecard comes from the evaluator on held-out data, never from model output.
- **A human approves.** Nothing ships without an explicit Approve, and the server enforces the safety gates rather than just greying out a button.
- **The default demo uses no LLM.** With `make run`, Red is a deterministic heuristic that reacts to which rules caught it, and Blue always returns the same known-good R4 patch from `fixtures/`. `make run-live` uses Gemini for both, and the UI labels which one actually ran.

## How robust the fix is

`make feasibility` checks R4 with no LLM involved. The full output is in [docs/feasibility-results.md](docs/feasibility-results.md).

- **Across seeds:** it passes the safety gate on **11 of 11 seeds**, each time with 0 new false positives and 8/48 → 32/48 attacks caught.
- **Across thresholds:** a lower hop count catches more but breaks things. 3 hops catches all 48 attacks and adds 1 false positive. 2 hops adds 242 false positives and fails the gate.

## Known limitations

- **Live agents:** steps run synchronously, so a live Red run (up to 4 LLM calls of up to 90 s each) shows no progress until it finishes. The frontend's proxy allows 300 s.
- **Remaining misses:** R4 misses 16 of the 48 attacks: every slow chain that holds money longer than 24 hours, and every chain that's too short. Fraud that forwards less than 40% at each hop (for example, by splitting it many ways) also slips past R4.
- **The baseline's false alarms:** v1 flags 9.8% of normal households at seed 7 (5.0–9.8% across seeds), all of them small businesses. R4 doesn't fix these.
- **Pre-funded mule accounts:** an account that sends money it already held, such as its opening balance, never trips R2.
- **No authentication:** anyone who can reach the API can approve. Red's free-text rationale could also reach Blue's prompt once Blue is a real LLM.
- **The test set isn't truly frozen:** it isn't retired after use. All of Blue's candidates are scored on it and the passing one is kept, which overstates how well the chosen fix generalizes.
- **Small numbers:** 48 attacks and 500 households are enough for a demo, not for claims about real-world accuracy.
