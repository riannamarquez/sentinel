"""SQLite store (design-v2 §4): one table per entity, JSON columns, WAL, append-only audit."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from sentinel.api.states import RunState, check_transition
from sentinel.schemas import (
    AuditEvent, BankConfig, BypassTrace, DetectionResult, DetectorVersion, EvaluationReport, Rule, RulePatch,
    canonical_json, sha256_of,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS labs (
    lab_id TEXT PRIMARY KEY,
    config_json TEXT NOT NULL,
    world_json TEXT NOT NULL,
    active_version INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS detector_versions (
    lab_id TEXT NOT NULL REFERENCES labs(lab_id),
    version INTEGER NOT NULL,
    rules_json TEXT NOT NULL,
    parent_version INTEGER,
    created_by_event_id TEXT NOT NULL,
    PRIMARY KEY (lab_id, version)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    lab_id TEXT NOT NULL REFERENCES labs(lab_id),
    state TEXT NOT NULL,
    base_version INTEGER NOT NULL,
    turns INTEGER NOT NULL DEFAULT 0,
    failure TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bypasses (
    bypass_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS patches (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    patch_id TEXT NOT NULL,
    json TEXT NOT NULL,
    error TEXT,
    PRIMARY KEY (run_id, patch_id)
);
CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    report_id TEXT PRIMARY KEY REFERENCES reports(report_id),
    decision TEXT NOT NULL,
    version_created INTEGER,
    event_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rechallenges (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    lab_id TEXT NOT NULL,
    run_id TEXT,
    timestamp INTEGER NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    input_hash TEXT,
    output_hash TEXT,
    version_before INTEGER,
    version_after INTEGER
);
CREATE TRIGGER IF NOT EXISTS audit_events_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS detector_versions_no_update BEFORE UPDATE ON detector_versions
BEGIN SELECT RAISE(ABORT, 'detector versions are never updated in place'); END;
CREATE TRIGGER IF NOT EXISTS detector_versions_no_delete BEFORE DELETE ON detector_versions
BEGIN SELECT RAISE(ABORT, 'detector versions are never deleted'); END;
"""


class NotFound(Exception):
    pass


class Conflict(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0, isolation_level=None, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    @contextmanager
    def tx(self):
        """One write transaction. BEGIN IMMEDIATE takes the write lock up front, so reads inside it
        cannot go stale before the writes land."""
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def journal_mode(self) -> str:
        with self._connect() as db:
            return db.execute("PRAGMA journal_mode").fetchone()[0]

    # --- audit ----------------------------------------------------------------------

    @staticmethod
    def audit(db, *, lab_id: str, actor: str, action: str, run_id: str | None = None, inp=None, out=None,
              version_before: int | None = None, version_after: int | None = None) -> str:
        """Append one event. Callers hold a BEGIN IMMEDIATE transaction, so MAX(seq) + 1 is safe."""
        seq = db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM audit_events").fetchone()[0]
        event_id = f"evt-{seq:08d}"
        db.execute(
            "INSERT INTO audit_events (seq, event_id, lab_id, run_id, timestamp, actor, action, input_hash,"
            " output_hash, version_before, version_after) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (seq, event_id, lab_id, run_id, int(time.time()), actor, action,
             None if inp is None else sha256_of(inp), None if out is None else sha256_of(out),
             version_before, version_after),
        )
        return event_id

    def audit_events(self, *, lab_id: str | None = None, run_id: str | None = None) -> list[AuditEvent]:
        q, args = "SELECT * FROM audit_events", []
        if run_id:
            q, args = q + " WHERE run_id = ?", [run_id]
        elif lab_id:
            q, args = q + " WHERE lab_id = ?", [lab_id]
        with self._connect() as db:
            rows = db.execute(q + " ORDER BY seq", args).fetchall()
        return [AuditEvent(event_id=r["event_id"], seq=r["seq"], timestamp=r["timestamp"], actor=r["actor"],
                           run_id=r["run_id"], action=r["action"], input_hash=r["input_hash"],
                           output_hash=r["output_hash"], version_before=r["version_before"],
                           version_after=r["version_after"]) for r in rows]

    # --- labs and versions -------------------------------------------------------------

    def create_lab(self, config: BankConfig, world_summary: dict, rules: list[Rule]) -> str:
        with self.tx() as db:
            n = db.execute("SELECT COUNT(*) FROM labs").fetchone()[0]
            lab_id = f"lab-{n + 1:04d}"
            config = config.model_copy(update={"lab_id": lab_id})
            db.execute("INSERT INTO labs VALUES (?, ?, ?, ?, ?)",
                       (lab_id, canonical_json(config), json.dumps(world_summary), config.detector_version,
                        int(time.time())))
            event_id = self.audit(db, lab_id=lab_id, actor="system:seed", action="seed_detector",
                                  inp=config, out=rules, version_after=config.detector_version)
            db.execute("INSERT INTO detector_versions VALUES (?, ?, ?, ?, ?)",
                       (lab_id, config.detector_version, canonical_json(rules), None, event_id))
        return lab_id

    def lab(self, lab_id: str) -> dict:
        with self._connect() as db:
            row = db.execute("SELECT * FROM labs WHERE lab_id = ?", (lab_id,)).fetchone()
        if row is None:
            raise NotFound(f"lab {lab_id}")
        return {"lab_id": lab_id, "config": BankConfig.model_validate_json(row["config_json"]),
                "world": json.loads(row["world_json"]), "active_version": row["active_version"]}

    def versions(self, lab_id: str) -> list[DetectorVersion]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM detector_versions WHERE lab_id = ? ORDER BY version", (lab_id,)).fetchall()
        return [DetectorVersion(version=r["version"], rules=json.loads(r["rules_json"]),
                                parent_version=r["parent_version"], created_by_event_id=r["created_by_event_id"])
                for r in rows]

    def rules(self, lab_id: str, version: int) -> list[Rule]:
        with self._connect() as db:
            row = db.execute("SELECT rules_json FROM detector_versions WHERE lab_id = ? AND version = ?",
                             (lab_id, version)).fetchone()
        if row is None:
            raise NotFound(f"detector version {version}")
        return [Rule.model_validate(r) for r in json.loads(row["rules_json"])]

    # --- runs ---------------------------------------------------------------------------

    def create_run(self, lab_id: str) -> str:
        with self.tx() as db:
            active = db.execute("SELECT active_version FROM labs WHERE lab_id = ?", (lab_id,)).fetchone()
            if active is None:
                raise NotFound(f"lab {lab_id}")
            n = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            run_id = f"run-{n + 1:06d}"
            db.execute("INSERT INTO runs (run_id, lab_id, state, base_version, created_at) VALUES (?, ?, ?, ?, ?)",
                       (run_id, lab_id, RunState.INITIALIZE_LAB, active[0], int(time.time())))
            self.audit(db, lab_id=lab_id, run_id=run_id, actor="system", action=f"enter:{RunState.INITIALIZE_LAB}",
                       version_before=active[0])
        return run_id

    def run(self, run_id: str, lab_id: str | None = None) -> dict:
        with self._connect() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None or (lab_id is not None and row["lab_id"] != lab_id):
            raise NotFound(f"run {run_id}")
        return dict(row) | {"state": RunState(row["state"])}

    def transition(self, run_id: str, target: RunState, *, actor: str = "system", inp=None, out=None,
                   failure: str | None = None, turns: int | None = None) -> None:
        with self.tx() as db:
            row = db.execute("SELECT lab_id, state, base_version FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            check_transition(RunState(row["state"]), target)
            db.execute("UPDATE runs SET state = ?, failure = COALESCE(?, failure), turns = COALESCE(?, turns) "
                       "WHERE run_id = ?", (target, failure, turns, run_id))
            self.audit(db, lab_id=row["lab_id"], run_id=run_id, actor=actor, action=f"enter:{target}",
                       inp=inp, out=out, version_before=row["base_version"])

    # --- step artifacts -----------------------------------------------------------------

    def save_bypass(self, run_id: str, trace: BypassTrace) -> None:
        with self.tx() as db:
            db.execute("INSERT INTO bypasses VALUES (?, ?, ?)", (trace.bypass_id, run_id, canonical_json(trace)))

    def bypass(self, bypass_id: str, run_id: str) -> BypassTrace:
        with self._connect() as db:
            row = db.execute("SELECT json FROM bypasses WHERE bypass_id = ? AND run_id = ?",
                             (bypass_id, run_id)).fetchone()
        if row is None:
            raise NotFound(f"bypass {bypass_id} in run {run_id}")
        return BypassTrace.model_validate_json(row["json"])

    def save_patch(self, run_id: str, patch: RulePatch, error: str | None) -> None:
        with self.tx() as db:
            db.execute("INSERT INTO patches VALUES (?, ?, ?, ?)", (run_id, patch.patch_id, canonical_json(patch), error))

    def patch(self, run_id: str, patch_id: str) -> tuple[RulePatch, str | None]:
        with self._connect() as db:
            row = db.execute("SELECT json, error FROM patches WHERE run_id = ? AND patch_id = ?",
                             (run_id, patch_id)).fetchone()
        if row is None:
            raise NotFound(f"patch {patch_id} in run {run_id}")
        return RulePatch.model_validate_json(row["json"]), row["error"]

    def save_report(self, report: EvaluationReport) -> None:
        with self.tx() as db:
            db.execute("INSERT INTO reports VALUES (?, ?, ?)", (report.report_id, report.run_id, canonical_json(report)))

    def next_report_id(self) -> str:
        with self._connect() as db:
            return f"rep-{db.execute('SELECT COUNT(*) FROM reports').fetchone()[0] + 1:06d}"

    def report(self, report_id: str) -> EvaluationReport:
        with self._connect() as db:
            row = db.execute("SELECT json FROM reports WHERE report_id = ?", (report_id,)).fetchone()
        if row is None:
            raise NotFound(f"report {report_id}")
        return EvaluationReport.model_validate_json(row["json"])

    def reports(self, lab_id: str) -> list[EvaluationReport]:
        with self._connect() as db:
            rows = db.execute("SELECT r.json FROM reports r JOIN runs u ON u.run_id = r.run_id WHERE u.lab_id = ? "
                              "ORDER BY r.report_id", (lab_id,)).fetchall()
        return [EvaluationReport.model_validate_json(r["json"]) for r in rows]

    def approval(self, report_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM approvals WHERE report_id = ?", (report_id,)).fetchone()
        return dict(row) if row else None

    def decide(self, lab_id: str, report: EvaluationReport, decision: str, new_rules: list[Rule] | None) -> dict:
        """Record a human decision atomically. Approve creates a version only if the lab's active
        version is still the one the report was evaluated against (optimistic concurrency)."""
        with self.tx() as db:
            if db.execute("SELECT 1 FROM approvals WHERE report_id = ?", (report.report_id,)).fetchone():
                raise Conflict("already_decided", report.report_id)
            active = db.execute("SELECT active_version FROM labs WHERE lab_id = ?", (lab_id,)).fetchone()[0]
            version_created = None
            if decision == "approve":
                if active != report.baseline_version:
                    raise Conflict("stale_base_version",
                                   f"report was evaluated against v{report.baseline_version}, active is v{active}")
                version_created = db.execute("SELECT MAX(version) FROM detector_versions WHERE lab_id = ?",
                                             (lab_id,)).fetchone()[0] + 1
                updated = db.execute("UPDATE labs SET active_version = ? WHERE lab_id = ? AND active_version = ?",
                                     (version_created, lab_id, report.baseline_version)).rowcount
                if updated != 1:
                    raise Conflict("stale_base_version")
            event_id = self.audit(db, lab_id=lab_id, run_id=report.run_id, actor="human", action=decision,
                                  inp={"report_id": report.report_id, "decision": decision},
                                  out=new_rules if version_created else None,
                                  version_before=active, version_after=version_created or active)
            if version_created:
                db.execute("INSERT INTO detector_versions VALUES (?, ?, ?, ?, ?)",
                           (lab_id, version_created, canonical_json(new_rules), report.baseline_version, event_id))
            db.execute("INSERT INTO approvals VALUES (?, ?, ?, ?)",
                       (report.report_id, decision, version_created, event_id))
        return {"decision": decision, "version_created": version_created, "event_id": event_id,
                "active_version": version_created or active}

    def save_rechallenge(self, run_id: str, result: DetectionResult) -> None:
        with self.tx() as db:
            db.execute("INSERT INTO rechallenges VALUES (?, ?)", (run_id, canonical_json(result)))

    def rechallenge(self, run_id: str) -> DetectionResult | None:
        with self._connect() as db:
            row = db.execute("SELECT json FROM rechallenges WHERE run_id = ?", (run_id,)).fetchone()
        return DetectionResult.model_validate_json(row["json"]) if row else None
