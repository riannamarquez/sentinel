# Backend 2

Implemented on `backend-2` using design-v2 §§3, 4, 6 and 7. The existing deterministic evaluator, integer-count gates, immutable detector versions, approval concurrency checks, and append-only SQLite audit remain the authority for decisions.

## Run

```sh
make install
make test
make run
```

The default is **fixture** mode: no credentials or network required. `/healthz` reports `fixture`, `live`, or `replay`. Red remains Backend 1's fixture implementation; the new adapter is wired to Blue.

The backend automatically loads `.env` from the current working directory when `create_app` runs. Run `make run` from the repository root. Existing environment variables take precedence; missing `.env` files are allowed. `.env` is gitignored, and `.env.example` contains no credentials.

For live Blue, copy `.env.example` to `.env` if you do not already have one, then set `SENTINEL_LLM_MODE=live`, fill in `GEMINI_API_KEY` and `SENTINEL_LLM_MODEL`, and run `make run`. Restart the server after editing `.env`.

You can also set the same configuration directly in your terminal:

```sh
export SENTINEL_LLM_MODE=live
export SENTINEL_LLM_PROVIDER=gemini
export SENTINEL_LLM_MODEL='<your Gemini model ID>'
export GEMINI_API_KEY='<your Gemini API key>'
make run
```

The default live transport is native Gemini `generateContent`, with `responseMimeType=application/json` and the proposal JSON schema in `responseJsonSchema`. It sends the key in `x-goog-api-key`, and validates the result locally with Pydantic. The model ID is required so the demo explicitly controls its model. Provider refusal, truncation, malformed envelopes, exhausted transport retries, or three invalid proposals fail closed. Transport retries and output-validation retries have separate limits within a single 90-second proposal deadline (`SENTINEL_LLM_TIMEOUT_SECONDS`). HTTP 408/429 and transient server failures are retried; permanent request/authentication errors fail immediately. The transport follows [Google’s structured output documentation](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).

`SENTINEL_LLM_PROVIDER=gateway` instead posts `{role, model, instructions, inputs, response_schema, prompt_version, validation_attempt}` to a custom gateway that must return the proposal JSON directly. No extra SDK is required. `SENTINEL_LLM_PROVIDER=chat` also supports Chat Completions JSON mode, using `SENTINEL_LLM_ENDPOINT` and `SENTINEL_LLM_API_KEY`.

`SENTINEL_DB` defaults to `sentinel.db`. `SENTINEL_LLM_DB` defaults to `<SENTINEL_DB>.llm.db`. Credentials are read from the environment, sent only as request headers, and excluded from recordings. The prompt is versioned in `sentinel/llm/prompts/blue_v1.md`; its exact contents, schema, evidence, model and explicit version contribute to the replay key. Blue receives structured transactions, diagnosis and feature bounds; Red's narrative and scenario labels are excluded.

## API

Existing synchronous request/response shapes still work with the frontend. For Blue or evaluation background execution, append `?background=true` to the corresponding POST. It returns **202** with `run_id` and `events_url`. Only one of these jobs can execute on a run at a time. Admission checks the run state inside the claim transaction. Background and synchronous requests share a four-step admission limit and two execution slots; excess work returns 503 with `Retry-After`, leaving the run available to retry.

- `POST /labs/{id}/patches`: `{run_id, bypass_id}` → up to three patch candidates with validation results.
- `POST /labs/{id}/evaluations`: `{run_id, patch_id}` → deterministic report. A report with failed gates still awaits a human rejection; approving it returns 409.
- `POST /labs/{id}/approvals`: `{report_id, decision}` → version or rejection, plus rechallenge. Stale-base checks and idempotency are enforced in the decision transaction. The detector change, decision state and pending rechallenge job commit together. Rechallenge uses the decision-time detector version. Simultaneous identical decisions return the same event. If completion fails, the response includes `completion_pending: true`; retry the identical decision or restart the server to resume it.
- `GET /runs/{run_id}`: state, failure, bypasses, patch validation results, reports, audit events and rechallenge. Use this to fetch results after a background step.
- `GET /runs/{run_id}/events`: SSE state events with persistent sequence IDs. Reconnect using `Last-Event-ID`. A stream closes at a terminal state or a step boundary awaiting another request; reconnect after submitting the next step. Events contain audit metadata; artifacts come from the run endpoint.
- `GET /labs/{id}/timeline`: regenerated deterministic world transactions, bypass transactions and audit events.
- `GET /labs/{id}/reports`: evaluator reports and detector history.
- `GET /labs/{id}/replay`: version-2 lab JSON from a single SQLite read snapshot, with configuration, versions, run-owned artifacts, approvals, audit events, and matching Blue recordings. Flat playback collections remain available. Blue recordings are committed before patch artifacts, then filtered to the snapshot’s bypass inputs. Recordings belonging to other lab inputs are excluded.

On startup, interrupted proposal/evaluation steps fail closed with an audit event; completed and human-waiting runs survive. Committed decisions with pending rechallenges resume without applying another version. Run a single Uvicorn process, as in `make run`; background work uses a bounded two-thread executor.

## Offline replay

Export a completed lab:

```sh
curl http://127.0.0.1:8000/labs/lab-0001/replay > /tmp/sentinel-replay.json
uv run --frozen python -m sentinel.replay /tmp/sentinel-replay.json
```

The verifier preserves each artifact’s run ownership, regenerates frozen splits and evaluator reports, checks candidate rule hashes, re-scores recorded bypasses and decision-version rechallenges, and replays Blue from bundled recordings. Runs that have not called Blue are also valid in a snapshot. Old version-1 exports must be exported again to get run ownership. It has no network transport. Missing or changed inputs, schema, prompt, model, candidate rules, or report metrics cause verification to fail. It does not claim to verify every historical audit hash or rerun Backend 1's Red search.

To run the API with a previously recorded Blue response store:

```sh
export SENTINEL_LLM_MODE=replay
export SENTINEL_LLM_MODEL='<same model used to record>'
export SENTINEL_LLM_DB='<recorded response database>'
make run
```

Replay misses raise an error and never fall back to live calls. API replay requires the identical evidence ID, transactions and base version; the portable bundle verifier reconstructs the exact recorded inputs.

## Scope still deferred

Design-v2 §9 still applies: authentication, holdout epochs/retirement and two-stage candidate selection are not part of this implementation. The structured Blue prompt removes direct forwarding of Red's rationale. Red's live search belongs to Backend 1. Live provider availability, credentials, model compatibility and patch quality must be checked with the chosen provider; automated tests use controlled transports without paid calls.
