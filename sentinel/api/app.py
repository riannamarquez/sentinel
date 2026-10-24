"""Walking-skeleton API (design-v2 §7). Agents are fixture stubs; steps run synchronously.

Run: make run   (or: uvicorn --factory sentinel.api.app:create_app). The database path comes from
SENTINEL_DB (default ./sentinel.db).
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from sentinel.agents import blue, red
from sentinel.api.states import InvalidTransition, RunState
from sentinel.api.store import Conflict, NotFound, Store
from sentinel.api.timeline import Timeline, build_timeline
from sentinel.detector.baseline import BASELINE_V1
from sentinel.detector.patches import PatchError, apply_patch
from sentinel.detector.score import diagnose, score
from sentinel.eval.evaluator import evaluate
from sentinel.fixtures import OBJECTIVE_CENTS, load_golden
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


class PatchRequest(Body):
    run_id: str
    bypass_id: str


class EvaluationRequest(Body):
    run_id: str
    patch_id: str


class ApprovalRequest(Body):
    report_id: str
    decision: Literal["approve", "reject"]


@lru_cache(maxsize=8)
def lab_splits(seed: int, benign_n: int, attack_copies: int) -> dict[Split, list]:
    """Deterministic, so caching by (seed, sizes) is safe; every evaluation of a lab sees the same splits."""
    return factory.build_splits(seed, benign_n, attack_copies)


def create_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="Sentinel", version="0.1.0")
    store = Store(db_path or os.environ.get("SENTINEL_DB", "sentinel.db"))
    app.state.store = store

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
        return {"ok": True, "llm": "stubbed", "journal_mode": store.journal_mode()}

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

        for turn in range(1, body.max_turns + 1):
            candidates = red.propose(body.objective_cents, rules, turn)
            store.transition(run_id, S.RED_PROPOSES, actor="agent:red", turns=turn,
                             out=[c.actions for c in candidates])
            valid, dropped = [], []
            for i, c in enumerate(candidates):
                try:
                    valid.append(apply_actions(
                        scenario_id=f"{run_id}.red.t{turn}.c{i}", template_id=c.template_id,
                        seed=derive_seed(lab["config"].seed, run_id, turn, i), split=Split.SEARCH,
                        start_ts=c.start_ts, source_account_id=c.source_account_id,
                        funding_cents=c.funding_cents, actions=c.actions))
                except ActionError as e:
                    dropped.append({"candidate": i, "reason": str(e)})   # logged and dropped, never repaired
            store.transition(run_id, S.VALIDATE_ACTIONS, out={"valid": len(valid), "dropped": dropped})
            results = [score(s, rules, version) for s in valid]
            store.transition(run_id, S.RUN_SIMULATION, out=results)
            bypasses = [(s, c) for s, d, c in zip(valid, results, candidates)
                        if not d.alert and moved_out_cents(s) >= body.objective_cents]
            store.transition(run_id, S.MEASURE_OUTCOME, out={"bypasses": len(bypasses)})
            if bypasses:
                scenario, cand = bypasses[0]
                trace = BypassTrace(
                    bypass_id=f"{run_id}.bypass", detector_version=version, scenario=scenario,
                    moved_cents=moved_out_cents(scenario), objective_cents=body.objective_cents,
                    why_it_worked=diagnose(scenario, rules), rationale=cand.rationale)
                store.save_bypass(run_id, trace)
                return {"run_id": run_id, "state": S.MEASURE_OUTCOME, "turns": turn, "bypass": trace}
        store.transition(run_id, S.NO_BYPASS_FOUND)
        return {"run_id": run_id, "state": S.NO_BYPASS_FOUND, "turns": body.max_turns, "bypass": None}

    @app.post("/labs/{lab_id}/patches", status_code=201)
    def patches(lab_id: str, body: PatchRequest):
        run = store.run(body.run_id, lab_id)
        require_state(run, S.MEASURE_OUTCOME)
        trace = store.bypass(body.bypass_id, body.run_id)
        rules = store.rules(lab_id, run["base_version"])
        proposed = blue.propose(trace, rules, run["base_version"])[:3]
        store.transition(body.run_id, S.BLUE_PROPOSES, actor="agent:blue", inp=trace, out=proposed)
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

    @app.post("/labs/{lab_id}/evaluations", status_code=201)
    def evaluations(lab_id: str, body: EvaluationRequest):
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

    def finish_round(lab_id: str, run_id: str, decision: str) -> None:
        """Apply new version / reject -> rechallenge -> complete, for a run still waiting on the human."""
        if store.run(run_id)["state"] is not S.AWAIT_HUMAN:
            return
        store.transition(run_id, S.APPLY_NEW_VERSION if decision == "approve" else S.REJECT_NO_CHANGE, actor="human")
        lab = store.lab(lab_id)
        version = lab["active_version"]
        # A fresh slow variant the run has never seen, against whichever version is now active.
        fresh = factory.attack_scenario(lab["config"].seed, Split.FINAL_HOLDOUT, "slow_chain_3",
                                        10_000 + int(run_id.split("-")[1]))
        result = score(fresh, store.rules(lab_id, version), version)
        store.save_rechallenge(run_id, result)
        store.transition(run_id, S.RECHALLENGE, out=result)
        store.transition(run_id, S.COMPLETE)

    @app.post("/labs/{lab_id}/approvals")
    def approvals(lab_id: str, body: ApprovalRequest):
        report = store.report(body.report_id)
        run = store.run(report.run_id, lab_id)
        previous = store.approval(body.report_id)
        if previous:
            if previous["decision"] != body.decision:
                raise Conflict("already_decided", f"report {body.report_id} was already {previous['decision']}d")
            finish_round(lab_id, run["run_id"], body.decision)   # idempotent retry
            result = {k: previous[k] for k in ("decision", "version_created", "event_id")}
        else:
            require_state(run, S.AWAIT_HUMAN)
            new_rules = None
            if body.decision == "approve":
                if not report.eligible_for_approval:
                    failed = [g.name for g in report.gate_results if not g.passed]
                    raise Conflict("gates_failed", f"failed gates: {failed}")
                patch, _ = store.patch(run["run_id"], report.patch_id)
                new_rules = apply_patch(store.rules(lab_id, report.baseline_version), patch)
            result = store.decide(lab_id, report, body.decision, new_rules)
            finish_round(lab_id, run["run_id"], body.decision)
        return {**result, "run_id": run["run_id"], "active_version": store.lab(lab_id)["active_version"],
                "rechallenge": store.rechallenge(run["run_id"])}

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
        return {**run, "events": store.audit_events(run_id=run_id), "rechallenge": store.rechallenge(run_id)}

    return app

