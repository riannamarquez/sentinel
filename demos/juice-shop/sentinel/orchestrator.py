"""Orchestrator — runs the full purple-team loop and records it.

    recon -> RED scans -> BLUE remediates -> VERIFY (replay) -> report

The output is a single run-log dict (serialisable to JSON) that the dashboard
reads. Keeping all state in one plain dict means the demo UI never has to know
anything about the agents — it just renders the log.
"""
from __future__ import annotations

import datetime as dt

from .blue_agent import BlueAgent
from .juice_shop import JuiceShopClient
from .models import Finding, Severity
from .red_agent import RedAgent, canned_findings


def _severity_breakdown(findings: list[Finding]) -> dict[str, int]:
    out = {s.value: 0 for s in Severity}
    for f in findings:
        out[f.severity.value] += 1
    return {k: v for k, v in out.items() if v}


def run_loop(target: str = "http://localhost:3000", mode: str = "live",
             allow_remote: bool = False, on_event=None) -> dict:
    """Execute the loop and return the run log.

    mode="live"   -> attack a running Juice Shop at ``target``.
    mode="replay" -> use canned findings so the demo runs with no target.
    """
    timeline: list[dict] = []

    def emit(kind: str, data: dict):
        event = {"t": dt.datetime.now().isoformat(timespec="seconds"),
                 "kind": kind, "data": data}
        timeline.append(event)
        if on_event:
            on_event(kind, data)

    version = None
    emit("recon", {"target": target, "mode": mode})

    # --- RED --------------------------------------------------------------
    if mode == "replay":
        findings = canned_findings()
        for f in findings:
            emit("finding", f.to_dict())
    else:
        client = JuiceShopClient(target, allow_remote=allow_remote)
        if not client.is_up():
            raise ConnectionError(
                f"No Juice Shop responding at {target}. Start it first "
                "(see the README) or run with --mode replay for an offline demo."
            )
        try:
            vr = client.get("/rest/admin/application-version")
            version = vr.json().get("version")
        except Exception:
            version = None
        red = RedAgent(client)
        findings = red.scan(on_event=emit)

    before = {"open": len(findings), "by_severity": _severity_breakdown(findings)}

    # --- BLUE -------------------------------------------------------------
    blue = BlueAgent()
    remediations = blue.remediate(findings, on_event=emit)

    # --- VERIFY (close the loop) -----------------------------------------
    # Replay every finding's recorded request through Blue's now-active controls.
    mitigated, residual = [], []
    for f in findings:
        blocked, rule = blue.engine.evaluate(f.evidence)
        (mitigated if blocked else residual).append(
            {"finding_id": f.id, "rule": rule, "severity": f.severity.value})
        emit("verify", {"finding_id": f.id, "mitigated": blocked, "rule": rule})

    after = {
        "open": len(residual),
        "mitigated": mitigated,
        "residual": residual,
    }
    emit("done", {"mitigated": len(mitigated), "residual": len(residual)})

    return {
        "tool": "Sentinel purple-team loop",
        "target": target,
        "mode": mode,
        "started_at": timeline[0]["t"],
        "juice_shop_version": version,
        "findings": [f.to_dict() for f in findings],
        "remediations": [r.to_dict() for r in remediations],
        "verification": {"before": before, "after": after},
        "timeline": timeline,
    }
