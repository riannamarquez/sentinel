"""Sentinel API (design-v2 §7). Blue supports live/fixture/replay and background execution.

Run: make run   (or: uvicorn --factory sentinel.api.app:create_app). The database path comes from
SENTINEL_DB (default ./sentinel.db). SENTINEL_RED picks Red's policy: "heuristic" (default) or "fixture".
"""
from __future__ import annotations

import os
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Literal

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from sentinel.agents import blue, red
from sentinel.api.bypass_replay import replay_bypass
from sentinel.api.states import InvalidTransition, RunState, TERMINAL
from sentinel.api.store import Conflict, NotFound, Store
from sentinel.api.timeline import Timeline, build_timeline
from sentinel.detector.baseline import BASELINE_V1
from sentinel.detector.explain import near_misses
from sentinel.detector.patches import PatchError, apply_patch
from sentinel.detector.score import diagnose, rules_fired, score
from sentinel.eval.evaluator import evaluate
from sentinel.fixtures import OBJECTIVE_CENTS, load_golden
from sentinel.llm.adapter import AdapterError, from_env, proposal_request
from sentinel.schemas import sha256_of
from sentinel.scenarios import factory
from sentinel.schemas import BankConfig, BypassTrace, Cents, Split
from sentinel.sim.actions import ActionError, apply_actions, moved_out_cents
from sentinel.sim.rng import derive_seed
from sentinel.sim.world import generate_world, world_summary

S = RunState
GOLDEN = ("caught_fraud", "missed_fraud_slow_variant", "legit_lookalike")


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RedRunRequest(Body):
    objective_cents: Cents = OBJECTIVE_CENTS
    max_turns: int = Field(default=4, ge=1, le=4)


class ReplayBypassRequest(Body):
    rules: Literal["base", "candidate", "active"]
    patch_id: str | None = None   # candidate only; defaults to the run's evaluated patch


class PatchRequest(Body):
    run_id: str
    bypass_id: str


class EvaluationRequest(Body):
    run_id: str
    patch_id: str


class ApprovalRequest(Body):
    report_id: str
    decision: Literal["approve", "reject"]


RED_POLICIES = {"heuristic": red.HeuristicRedPolicy, "fixture": red.FixtureRedPolicy}


def red_policy_from_env() -> red.FixtureRedPolicy | red.HeuristicRedPolicy:
    name = os.environ.get("SENTINEL_RED", "heuristic")
    if name not in RED_POLICIES:
        raise ValueError(f"SENTINEL_RED={name!r}; expected one of {sorted(RED_POLICIES)}")
    return RED_POLICIES[name]()


@lru_cache(maxsize=8)
def lab_splits(seed: int, benign_n: int, attack_copies: int) -> dict[Split, list]:
    """Deterministic, so caching by (seed, sizes) is safe; every evaluation of a lab sees the same splits."""
    return factory.build_splits(seed, benign_n, attack_copies)


def create_app(db_path: str | None = None, red_policy=None, *, adapter=None) -> FastAPI:
    red_policy = red_policy or red_policy_from_env() # if sentinel_red fails at start up
    db_path = db_path or os.environ.get("SENTINEL_DB", "sentinel.db")
    store = Store(db_path)
    adapter = adapter if adapter is not None else from_env(db_path)
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sentinel")
    slots = BoundedSemaphore(4)  # total admitted background + synchronous steps
    workers = BoundedSemaphore(2)

    @asynccontextmanager
    async def lifespan(app):
        store.recover_interrupted()
        for job in store.pending_completions():
            try:
                finish_round(job['run_id'])
            except Exception:
                logging.getLogger(__name__).exception('Pending rechallenge will retry on next approval request')
        yield
        executor.shutdown(wait=True)

    app = FastAPI(title="Sentinel", version="0.2.0", lifespan=lifespan)
    app.state.store = store
    app.state.adapter = adapter

    @app.exception_handler(NotFound)
    def _not_found(request: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"reason": "not_found", "detail": str(exc)})

    @app.exception_handler(Conflict)
    def _conflict(request: Request, exc: Conflict):
        return JSONResponse(status_code=409, content={"reason": exc.reason, "detail": exc.detail})

    @app.exception_handler(InvalidTransition)
    def _invalid(request: Request, exc: InvalidTransition):
        return JSONResponse(status_code=409, content={"reason": "invalid_transition", "detail": str(exc)})

    def require_state(run: dict, *allowed: RunState) -> None:
        if run["state"] not in allowed:
            raise Conflict("invalid_state", f"run {run['run_id']} is {run['state']}, needs {[str(a) for a in allowed]}")

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "llm": adapter.mode if adapter else "fixture", "journal_mode": store.journal_mode()}

    @app.post("/labs", status_code=201)
    def create_lab(config: BankConfig):
        if config.detector_version != 1:
            raise Conflict("unsupported", "labs start from detector v1")
        summary = world_summary(generate_world(config))
        lab_id = store.create_lab(config, summary, BASELINE_V1)
        return {"lab_id": lab_id, "world": summary, "active_detector_version": 1}

    @app.get("/labs/{lab_id}")
    def get_lab(lab_id: str):
        lab = store.lab(lab_id)
        return {**lab, "versions": store.versions(lab_id)}

    @app.post("/labs/{lab_id}/baseline")
    def baseline(lab_id: str):
        version = store.lab(lab_id)["active_version"]
        rules = store.rules(lab_id, version)
        return {"detector_version": version,
                "results": [score(load_golden(name)[0], rules, version) for name in GOLDEN]}

    @app.post("/labs/{lab_id}/red-runs", status_code=201)
    def red_run(lab_id: str, body: RedRunRequest):
        lab = store.lab(lab_id)
        run_id = store.create_run(lab_id)
        version = store.run(run_id)["base_version"]
        rules = store.rules(lab_id, version)
        store.transition(run_id, S.GENERATE_WORLD, out=lab["world"])
        store.transition(run_id, S.BASELINE_SCORE, out=rules)

        history: list[red.Attempt] = []
        for turn in range(1, body.max_turns + 1):
            candidates = red_policy.propose(objective_cents=body.objective_cents, rules=rules, turn=turn,
                                            history=history, seed=lab["config"].seed, run_id=run_id)
            store.transition(run_id, S.RED_PROPOSES, actor="agent:red", turns=turn,
                             out=[c.actions for c in candidates])
            valid, dropped = [], []
            for i, c in enumerate(candidates):
                try:
                    scenario = apply_actions(
                        scenario_id=f"{run_id}.red.t{turn}.c{i}", template_id=c.template_id,
                        seed=derive_seed(lab["config"].seed, run_id, turn, i), split=Split.SEARCH,
                        start_ts=c.start_ts, source_account_id=c.source_account_id,
                        funding_cents=c.funding_cents, actions=c.actions)
                    valid.append((scenario, c))
                except ActionError as e:
                    dropped.append({"candidate": i, "reason": str(e)})   # logged and dropped, never repaired
            store.transition(run_id, S.VALIDATE_ACTIONS, out={"valid": len(valid), "dropped": dropped})
            results = [score(s, rules, version) for s, _ in valid]
            store.transition(run_id, S.RUN_SIMULATION, out=results)
            bypasses = [(s, c) for (s, c), d in zip(valid, results)
                        if not d.alert and moved_out_cents(s) >= body.objective_cents]
            # rules_fired, not score().triggered_rule_ids: score() stops at the first alert and hides the rest.
            # Dropped candidates never get here, so they can't pose as a bypass with no rules fired.
            attempts = [red.Attempt(turn=turn, recipe=c.recipe, rules_fired=sorted(rules_fired(s, rules)),
                                    moved_cents=moved_out_cents(s), near_misses=near_misses(s, rules))
                        for s, c in valid if c.recipe is not None]
            history.extend(attempts)
            store.transition(run_id, S.MEASURE_OUTCOME, out={"bypasses": len(bypasses), "attempts": attempts})
            if bypasses:
                scenario, cand = bypasses[0]
                trace = BypassTrace(
                    bypass_id=f"{run_id}.bypass", detector_version=version, scenario=scenario,
                    moved_cents=moved_out_cents(scenario), objective_cents=body.objective_cents,
                    why_it_worked=diagnose(scenario, rules), rationale=cand.rationale)
                store.save_bypass(run_id, trace)
                return {"run_id": run_id, "state": S.MEASURE_OUTCOME, "turns": turn, "bypass": trace,
                        "history": [a.model_dump() for a in history]}
        store.transition(run_id, S.NO_BYPASS_FOUND)
        return {"run_id": run_id, "state": S.NO_BYPASS_FOUND, "turns": body.max_turns, "bypass": None,
                "history": [a.model_dump() for a in history]}

    def process_patches(lab_id: str, body: PatchRequest):
        run = store.run(body.run_id, lab_id)
        require_state(run, S.MEASURE_OUTCOME)
        trace = store.bypass(body.bypass_id, body.run_id)
        rules = store.rules(lab_id, run["base_version"])
        store.transition(body.run_id, S.BLUE_PROPOSES, actor="agent:blue", inp=trace)
        try:
            proposed = (blue.propose(trace, rules, run["base_version"], adapter=adapter) if adapter
                        else blue.propose(trace, rules, run["base_version"]))
        except AdapterError:
            store.transition(body.run_id, S.FAILED, failure="Blue proposal failed; evidence in LLM recording store")
            raise Conflict("proposal_failed", "Blue proposal failed closed")
        out = []
        for p in proposed:
            error = None
            try:
                if p.base_version != run["base_version"]:
                    raise PatchError(f"patch is based on v{p.base_version}, run is on v{run['base_version']}")
                apply_patch(rules, p)
            except PatchError as e:
                error = str(e)   # rejected before evaluation (US-06)
            store.save_patch(body.run_id, p, error)
            out.append({"patch": p, "valid": error is None, "error": error})
        if not any(o["valid"] for o in out):
            store.transition(body.run_id, S.FAILED, failure="no valid patch")
            return {"run_id": body.run_id, "state": S.FAILED, "patches": out}
        store.transition(body.run_id, S.VALIDATE_PATCH, out=out)
        return {"run_id": body.run_id, "state": S.VALIDATE_PATCH, "patches": out}

    def process_evaluation(lab_id: str, body: EvaluationRequest):
        run = store.run(body.run_id, lab_id)
        require_state(run, S.VALIDATE_PATCH)
        patch, error = store.patch(body.run_id, body.patch_id)
        if error:
            raise Conflict("invalid_patch", error)
        config = store.lab(lab_id)["config"]
        base_rules = store.rules(lab_id, run["base_version"])
        store.transition(body.run_id, S.EVALUATE_HOLDOUTS, inp=patch)
        report = evaluate(
            report_id=store.next_report_id(), run_id=body.run_id, patch_id=patch.patch_id,
            splits=lab_splits(config.seed, config.holdout_benign_n, config.holdout_attack_copies),
            baseline_rules=base_rules, baseline_version=run["base_version"],
            candidate_rules=apply_patch(base_rules, patch))
        store.transition(body.run_id, S.APPLY_GATES, out=report.gate_results)
        store.save_report(report)
        store.transition(body.run_id, S.AWAIT_HUMAN, out=report)
        return report

    def finish_round(run_id: str) -> None:
        jobs = store.pending_completions(run_id)
        if not jobs:
            return
        job = jobs[0]
        lab = store.lab(job['lab_id'])
        version = job['detector_version']
        fresh = factory.attack_scenario(lab['config'].seed, Split.FINAL_HOLDOUT, 'slow_chain_3',
                                        10_000 + int(run_id.split('-')[1]))
        store.complete_decision(run_id, score(fresh, store.rules(job['lab_id'], version), version))

    @app.post("/labs/{lab_id}/runs/{run_id}/replay-bypass")
    def replay_bypass_route(lab_id: str, run_id: str, body: ReplayBypassRequest):
        """Red's bypass re-scored against the run's base rules, base + its patch, or the lab's active rules."""
        run = store.run(run_id, lab_id)
        trace = store.bypass_for_run(run_id)
        if trace is None:
            raise Conflict("no_bypass", f"run {run_id} has no bypass to replay")
        base = run["base_version"]
        if body.rules == "base":
            return replay_bypass(trace, store.rules(lab_id, base), run_id=run_id, choice="base",
                                 label=f"Detector v{base}", version=base)
        if body.rules == "active":
            active = store.lab(lab_id)["active_version"]
            return replay_bypass(trace, store.rules(lab_id, active), run_id=run_id, choice="active",
                                 label=f"Detector v{active}", version=active)

        artifacts = store.run_artifacts(run_id)
        patch_id = body.patch_id
        if patch_id is None:   # the latest evaluated patch if there is one, else the run's first valid patch
            evaluated = [r["patch_id"] for r in artifacts["reports"]]
            valid = [p["patch"]["patch_id"] for p in artifacts["patches"] if p["valid"]]
            if evaluated:
                patch_id = evaluated[-1]
            elif valid:
                patch_id = valid[0]
            else:
                raise Conflict("no_valid_patch", f"run {run_id} has no valid patch yet; ask Blue for a fix first")
        patch, error = store.patch(run_id, patch_id)
        if error:
            raise Conflict("invalid_patch", error)
        # Approved candidates carry the version they became; unapproved ones have none.
        approved = [store.approval(r["report_id"]) for r in artifacts["reports"] if r["patch_id"] == patch_id]
        version = next((a["version_created"] for a in approved
                        if a and a["decision"] == "approve" and a["version_created"]), None)
        label = f"Detector v{version}" if version else f"Detector v{base} + proposed fix"
        return replay_bypass(trace, apply_patch(store.rules(lab_id, base), patch), run_id=run_id,
                             choice="candidate", label=label, version=version, patch_id=patch_id)

    @app.post("/labs/{lab_id}/approvals")
    def approvals(lab_id: str, body: ApprovalRequest):
        report = store.report(body.report_id)
        run = store.run(report.run_id, lab_id)
        new_rules = None
        if body.decision == 'approve':
            patch, _ = store.patch(run['run_id'], report.patch_id)
            new_rules = apply_patch(store.rules(lab_id, report.baseline_version), patch)
        result = store.decide(lab_id, report, body.decision, new_rules)
        try:
            finish_round(run['run_id'])
        except Exception:
            # The decision is already durable. Report pending completion honestly.
            logging.getLogger(__name__).exception('Rechallenge pending for %s', run['run_id'])
        return {**result, 'run_id': run['run_id'], 'active_version': store.lab(lab_id)['active_version'],
                'completion_pending': bool(store.pending_completions(run['run_id'])),
                'rechallenge': store.rechallenge(run['run_id'])}

    @app.get("/labs/{lab_id}/reports")
    def reports(lab_id: str):
        store.lab(lab_id)
        return {"reports": store.reports(lab_id), "versions": store.versions(lab_id)}

    @app.get("/labs/{lab_id}/timeline", response_model=Timeline)
    def get_timeline(lab_id: str, run_id: str, version: int | None = None):
        run = store.run(run_id, lab_id)
        version = run["base_version"] if version is None else version
        rules = store.rules(lab_id, version)
        trace = store.bypass_for_run(run_id)
        if trace is None:
            raise NotFound(f"no bypass for run {run_id}")
        return build_timeline(trace.scenario, rules, lab_id=lab_id, run_id=run_id, version=version,
                              objective_cents=trace.objective_cents,
                              background_accounts=store.lab(lab_id)["world"]["accounts"])

    @app.get("/runs/{run_id}")
    def get_run(run_id: str):
        run = store.run(run_id)
        return {**run, **store.run_artifacts(run_id), "events": store.audit_events(run_id=run_id),
                "rechallenge": store.rechallenge(run_id)}

    def claim_step(run_id, expected_state):
        if not slots.acquire(blocking=False):
            raise HTTPException(status_code=503, headers={'Retry-After': '1'},
                                detail={'reason': 'queue_full', 'detail': 'retry when a worker slot is available'})
        try:
            if not store.claim_job(run_id, expected_state):
                raise Conflict('step_running', 'a step is already running for this run')
        except Exception:
            slots.release()
            raise

    def submit(run_id, fn, *args):
        claim_step(run_id, S.MEASURE_OUTCOME if fn == process_patches else S.VALIDATE_PATCH)
        def work():
            try:
                with workers:
                    fn(*args)
            except Exception:
                current = store.run(run_id)["state"]
                if current not in TERMINAL:
                    store.transition(run_id, S.FAILED, failure="step failed; no detector version applied")
            finally:
                store.release_job(run_id)
                slots.release()
        try:
            executor.submit(work)
        except RuntimeError:
            store.release_job(run_id)
            slots.release()
            raise Conflict('server_stopping')
        return JSONResponse(status_code=202, content={"run_id": run_id, "events_url": f"/runs/{run_id}/events"})

    @app.post("/labs/{lab_id}/patches", status_code=201)
    def patches(lab_id: str, body: PatchRequest, background: bool = False):
        require_state(store.run(body.run_id, lab_id), S.MEASURE_OUTCOME)
        store.bypass(body.bypass_id, body.run_id)
        if background:
            return submit(body.run_id, process_patches, lab_id, body)
        claim_step(body.run_id, S.MEASURE_OUTCOME)
        try:
            with workers:
                return process_patches(lab_id, body)
        except Exception:
            if store.run(body.run_id)['state'] == S.BLUE_PROPOSES:
                store.transition(body.run_id, S.FAILED, failure='Blue proposal failed closed')
            raise
        finally:
            store.release_job(body.run_id)
            slots.release()

    @app.post("/labs/{lab_id}/evaluations", status_code=201)
    def evaluations(lab_id: str, body: EvaluationRequest, background: bool = False):
        require_state(store.run(body.run_id, lab_id), S.VALIDATE_PATCH)
        _, error = store.patch(body.run_id, body.patch_id)
        if error:
            raise Conflict("invalid_patch", error)
        if background:
            return submit(body.run_id, process_evaluation, lab_id, body)
        claim_step(body.run_id, S.VALIDATE_PATCH)
        try:
            with workers:
                return process_evaluation(lab_id, body)
        except Exception:
            if store.run(body.run_id)["state"] in {S.EVALUATE_HOLDOUTS, S.APPLY_GATES}:
                store.transition(body.run_id, S.FAILED, failure="evaluation failed closed")
            raise
        finally:
            store.release_job(body.run_id)
            slots.release()

    @app.get("/runs/{run_id}/events")
    async def events(run_id: str, request: Request):
        store.run(run_id)
        try:
            after = int(request.headers.get("last-event-id", "0"))
            if after < 0:
                raise ValueError()
        except ValueError:
            return JSONResponse(status_code=400, content={"reason": "invalid_event_id"})

        async def stream():
            cursor = after
            while not await request.is_disconnected():
                for event in store.audit_events(run_id=run_id):
                    if event.seq > cursor:
                        yield f"id: {event.seq}\nevent: state\ndata: {event.model_dump_json()}\n\n"
                        cursor = event.seq
                state = store.run(run_id)["state"]
                if state in TERMINAL or (state in {S.AWAIT_HUMAN, S.MEASURE_OUTCOME, S.VALIDATE_PATCH}
                                         and not store.job_running(run_id)):
                    # A worker can commit its last event between our poll and state read.
                    for event in store.audit_events(run_id=run_id):
                        if event.seq > cursor:
                            yield f"id: {event.seq}\nevent: state\ndata: {event.model_dump_json()}\n\n"
                            cursor = event.seq
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.2)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/labs/{lab_id}/replay")
    def replay(lab_id: str):
        bundle = store.export_lab(lab_id)
        bundle["llm_mode"] = adapter.mode if adapter else "fixture"
        if adapter:
            keys = set()
            for trace_json in bundle["bypasses"]:
                trace = BypassTrace.model_validate(trace_json)
                rules = store.rules(lab_id, trace.detector_version)
                request = proposal_request('blue', blue.prompt_inputs(trace, rules, trace.detector_version),
                                           blue.BlueProposal, 'blue-v1')
                request['model'] = adapter.model
                keys.add(sha256_of(request))
            bundle["llm_model"] = adapter.model
            bundle["llm_recordings"] = [r for r in adapter.store.export() if r['input_hash'] in keys]
        return bundle

    @app.get("/labs/{lab_id}/world")
    def world_view(lab_id: str):
        lab = store.lab(lab_id)
        world = generate_world(lab["config"])
        bundle = store.export_lab(lab_id)
        txns = {t.transaction_id: t.model_dump(mode="json") for t in world.transactions}
        for bypass in bundle["bypasses"]:
            for txn in bypass["scenario"]["transactions"]:
                txns[txn["transaction_id"]] = txn
        return {"lab_id": lab_id, "accounts": world.accounts,
                "transactions": sorted(txns.values(), key=lambda t: (t["timestamp"], t["transaction_id"])),
                "events": bundle["events"]}

    return app

