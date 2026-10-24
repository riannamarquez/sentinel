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
};
export type Decision = "approve" | "reject";
export type Approval = {
  decision: Decision;
  version_created: number | null;
  active_version: number;
  rechallenge: { alert: boolean; triggered_rule_ids: string[] } | null;
};

// Plain-English messages for the approval endpoint's 409 reasons.
const CONFLICTS: Record<string, string> = {
  gates_failed: "This fix can't be approved because at least one safety check failed.",
  already_decided: "A decision was already made on this report, so it can't be changed.",
  stale_base_version: "The detector changed since this fix was tested. Run a new round against the current rules.",
};

async function post(path: string, label: string, body?: unknown) {
  const res = await fetch(`/api${path}`, body === undefined ? { method: "POST" } : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${label} failed (${res.status})`);
  return res.json();
}

export function createLab(seed: number, accountCount: number): Promise<Lab> {
  return post("/labs", "Create lab", { seed, account_count: accountCount });
}

export async function runBaseline(labId: string): Promise<BaselineResult[]> {
  return (await post(`/labs/${labId}/baseline`, "Baseline")).results;
}

export async function startRedRun(labId: string): Promise<RedRun> {
  const data = await post(`/labs/${labId}/red-runs`, "Red challenge", {});
  return { run_id: data.run_id, turns: data.turns, bypass: data.bypass };
}

export async function proposePatches(labId: string, runId: string, bypassId: string): Promise<PatchRun> {
  const data = await post(`/labs/${labId}/patches`, "Blue fix", { run_id: runId, bypass_id: bypassId });
  return { state: data.state, patches: data.patches };
}

export function evaluatePatch(labId: string, runId: string, patchId: string): Promise<EvaluationReport> {
  return post(`/labs/${labId}/evaluations`, "Evaluation", { run_id: runId, patch_id: patchId });
}

export async function decide(labId: string, reportId: string, decision: Decision): Promise<Approval> {
  const res = await fetch(`/api/labs/${labId}/approvals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ report_id: reportId, decision }),
  });
  if (res.status === 409) {
    const body = await res.json().catch(() => ({}));
    throw new Error(CONFLICTS[body.reason] ?? body.detail ?? "This decision conflicts with the lab's current state.");
  }
  if (!res.ok) throw new Error(`Decision failed (${res.status})`);
  const data = await res.json();
  return {
    decision: data.decision,
    version_created: data.version_created,
    active_version: data.active_version,
    rechallenge: data.rechallenge,
  };
}
