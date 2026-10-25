// Typed wrappers around the backend, proxied through /api by next.config.ts.

export type World = { customers: number; accounts: number; transactions: number; edges: number };
export type Lab = { lab_id: string; world: World; active_detector_version: number };
export type BaselineResult = {
  scenario_id: string;
  alert: boolean;
  triggered_rule_ids: string[];
};
export type Transaction = {
  transaction_id: string;
  from_id: string;
  to_id: string;
  amount_cents: number;
  timestamp: number; // seconds
  ground_truth_label: string;
};
export type ConditionDiagnosis = {
  feature_key: string;
  operator: string;
  threshold: number;
  closest_value: number;
  held: boolean;
};
export type Bypass = {
  bypass_id: string;
  scenario: { transactions: Transaction[]; owned_account_ids: string[] };
  moved_cents: number;
  objective_cents: number;
  why_it_worked: { rule_id: string; conditions: ConditionDiagnosis[] }[];
  detector_version: number;
  rationale: string;
};
// Which policy produced a Red turn; "heuristic_fallback" carries why the LLM's turn was replaced.
export type TurnSource = { turn: number; policy: string; reason?: string; detail?: string };
// `rules` is the detector version Red attacked (bypass.detector_version), read from the lab.
export type RedRun = { run_id: string; turns: number; bypass: Bypass | null; rules: Rule[] | null; turn_sources: TurnSource[] };
export type Rule = { rule_id: string; all_of: Condition[] };
export type Condition = {
  feature_key: string;
  operator: string;
  threshold: number;
  window_hours?: number | null;
  params?: Record<string, number>;
};
export type RulePatch = {
  patch_id: string;
  operation: "add" | "modify" | "disable";
  rule_id: string | null;
  all_of: Condition[] | null;
  rationale: string;
};
export type PatchResult = { patch: RulePatch; valid: boolean; error: string | null };
export type BlueSource = "llm_live" | "llm_replay" | "fixture";
export type PatchRun = { state: string; patches: PatchResult[]; source: BlueSource | null };
export type Confusion = { tp: number; fp: number; tn: number; fn: number };
export type GateResult = { name: string; passed: boolean; detail: string; numerator: number; denominator: number; threshold: number };
export type EvaluationReport = {
  report_id: string;
  patch_id: string;
  benign_n: number;
  attack_n: number;
  baseline_confusion: Record<string, Confusion>;
  candidate_confusion: Record<string, Confusion>;
  gate_results: GateResult[];
  eligible_for_approval: boolean;
  missed_breakdown?: MissReason[]; // absent from older backends
};
export type MissReason = { reason: string; label: string; count: number };
export type Decision = "approve" | "reject";
export type Rechallenge = { alert: boolean; triggered_rule_ids: string[] };
export type Approval = {
  decision: Decision;
  version_created: number | null;
  active_version: number;
  completion_pending: boolean;   // the decision is saved but the rechallenge hasn't run yet
  rechallenge: Rechallenge | null;
};
export type AuditEvent = {
  event_id: string;
  seq: number;
  timestamp: number;            // wall-clock seconds
  actor: string;
  action: string;
  version_before: number | null;
  version_after: number | null;
};
// GET /runs/{run_id}: the run's state and its append-only audit events.
export type RunRecord = { run_id: string; state: string; events: AuditEvent[]; rechallenge: Rechallenge | null };
export type ReplayChoice = "base" | "candidate" | "active";
export type HopReplay = { hop_index: number; transaction_id: string; scored: boolean; alerted: boolean; rule_ids: string[] };
// Red's bypass re-scored by the backend against a chosen rule set; the frontend never scores rules itself.
export type BypassReplay = {
  rules: ReplayChoice;
  detector_label: string;
  detector_version: number | null;
  patch_id: string | null;
  alert: boolean;
  triggered_rule_ids: string[];
  first_alert_time: number | null;
  alert_transaction_id: string | null;
  alert_hop_index: number | null;
  per_hop: HopReplay[];
};

const UNREACHABLE = "Can't reach the Sentinel backend. Is `make run` running in the repo folder?";

// Plain-English sentences for the backend's error codes (the `reason` field).
const REASONS: Record<string, string> = {
  gates_failed: "This fix can't be approved because at least one safety check failed.",
  already_decided: "A decision was already made on this report, so it can't be changed.",
  stale_base_version: "The detector changed since this fix was tested. Run a new round against the current rules.",
  invalid_patch: "That fix was rejected as invalid, so it can't be evaluated.",
  invalid_state: "This step is out of order for the current round.",
  invalid_transition: "The round can't move to that step from where it is now.",
  not_found: "The backend doesn't know this lab or run. It may have restarted, so create a new lab.",
  unsupported: "The backend doesn't support that request.",
  proposal_failed: "Blue couldn't produce a valid fix. Try again.",
  step_running: "That step is still running — wait a moment.",
  server_stopping: "The backend is restarting. Try again in a few seconds.",
  queue_full: "The server is busy. Try again in a moment.",
  no_bypass: "Red didn't find a bypass in this run, so there's nothing to replay.",
  no_valid_patch: "There's no valid fix to replay yet. Ask Blue for a fix first.",
};

// What the UI shows: a plain-English sentence, plus the server's detail when it sent one.
export class ApiError extends Error {
  constructor(message: string, readonly detail: string | null = null) {
    super(message);
  }
}

// FastAPI sends `detail` as a string, or as a list of {msg} for request validation errors.
function detailText(detail: unknown): string | null {
  if (typeof detail === "string") return detail || null;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? JSON.stringify(d)).join("; ") || null;
  return null;
}

// POSTs `body` (or nothing) to the backend; method "GET" sends no body.
async function request(path: string, body?: unknown, method: "GET" | "POST" = "POST") {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, body === undefined ? { method } : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(UNREACHABLE);
  }
  const data = await res.json().catch(() => null);
  if (res.ok) {
    if (data === null) throw new ApiError(`Something went wrong (status ${res.status})`, "The backend sent a response that isn't JSON.");
    return data;
  }
  if (data === null && [500, 502, 503, 504].includes(res.status)) throw new ApiError(UNREACHABLE);
  // Most errors are {reason, detail}; a few (e.g. queue_full's 503) nest them: {detail: {reason, detail}}.
  const nested = data?.detail && typeof data.detail === "object" && !Array.isArray(data.detail) ? data.detail : null;
  const reason = REASONS[data?.reason ?? nested?.reason];
  const detail = detailText(nested ? nested.detail : data?.detail);
  throw new ApiError(reason ?? `Something went wrong (status ${res.status})`, detail);
}

export function createLab(seed: number, accountCount: number): Promise<Lab> {
  return request("/labs", { seed, account_count: accountCount });
}

export async function runBaseline(labId: string): Promise<BaselineResult[]> {
  return (await request(`/labs/${labId}/baseline`)).results;
}

// The rule definitions of one detector version, from the lab's version history.
export async function getRules(labId: string, version: number): Promise<Rule[] | null> {
  const lab = await request(`/labs/${labId}`, undefined, "GET");
  return lab.versions?.find((v: { version: number }) => v.version === version)?.rules ?? null;
}

export async function startRedRun(labId: string): Promise<RedRun> {
  const data = await request(`/labs/${labId}/red-runs`, {});
  const bypass: Bypass | null = data.bypass;
  const rules = bypass ? await getRules(labId, bypass.detector_version) : null;
  return { run_id: data.run_id, turns: data.turns, bypass, rules, turn_sources: data.turn_sources ?? [] };
}

export function replayBypass(labId: string, runId: string, rules: ReplayChoice): Promise<BypassReplay> {
  return request(`/labs/${labId}/runs/${runId}/replay-bypass`, { rules });
}

export function getRun(runId: string): Promise<RunRecord> {
  return request(`/runs/${runId}`, undefined, "GET");
}

export async function getRechallenge(runId: string): Promise<Rechallenge | null> {
  return (await getRun(runId)).rechallenge ?? null;
}

export async function proposePatches(labId: string, runId: string, bypassId: string): Promise<PatchRun> {
  const data = await request(`/labs/${labId}/patches`, { run_id: runId, bypass_id: bypassId });
  return { state: data.state, patches: data.patches, source: data.source ?? null };
}

export function evaluatePatch(labId: string, runId: string, patchId: string): Promise<EvaluationReport> {
  return request(`/labs/${labId}/evaluations`, { run_id: runId, patch_id: patchId });
}

export async function decide(labId: string, reportId: string, decision: Decision): Promise<Approval> {
  const data = await request(`/labs/${labId}/approvals`, { report_id: reportId, decision });
  return {
    decision: data.decision,
    version_created: data.version_created,
    active_version: data.active_version,
    completion_pending: !!data.completion_pending,
    rechallenge: data.rechallenge ?? null,
  };
}
