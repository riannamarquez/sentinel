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
  scenario: { transactions: Transaction[] };
  moved_cents: number;
  objective_cents: number;
  why_it_worked: { rule_id: string; conditions: ConditionDiagnosis[] }[];
  rationale: string;
};
export type RedRun = { run_id: string; turns: number; bypass: Bypass | null };
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
export type PatchRun = { state: string; patches: PatchResult[] };
export type Confusion = { tp: number; fp: number; tn: number; fn: number };
export type GateResult = { name: string; passed: boolean; detail: string };
export type EvaluationReport = {
  report_id: string;
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
export type Approval = {
  decision: Decision;
  version_created: number | null;
  active_version: number;
  rechallenge: { alert: boolean; triggered_rule_ids: string[] } | null;
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

async function request(path: string, body?: unknown) {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, body === undefined ? { method: "POST" } : {
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
  const detail = detailText(data?.detail);
  const reason = REASONS[data?.reason];
  throw new ApiError(reason ?? `Something went wrong (status ${res.status})`, detail);
}

export function createLab(seed: number, accountCount: number): Promise<Lab> {
  return request("/labs", { seed, account_count: accountCount });
}

export async function runBaseline(labId: string): Promise<BaselineResult[]> {
  return (await request(`/labs/${labId}/baseline`)).results;
}

export async function startRedRun(labId: string): Promise<RedRun> {
  const data = await request(`/labs/${labId}/red-runs`, {});
  return { run_id: data.run_id, turns: data.turns, bypass: data.bypass };
}

export async function proposePatches(labId: string, runId: string, bypassId: string): Promise<PatchRun> {
  const data = await request(`/labs/${labId}/patches`, { run_id: runId, bypass_id: bypassId });
  return { state: data.state, patches: data.patches };
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
    rechallenge: data.rechallenge,
  };
}
