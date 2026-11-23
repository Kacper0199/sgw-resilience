import { HttpResponse, http } from "msw";
import { meFor } from "@/mocks/fixtures";
import { mockState } from "@/mocks/handlers";
import { toLiveRun, toLiveStep } from "./adaptRuns";
import agentRuns from "./mocks/agent-runs.json";
import aiConfig from "./mocks/ai-config.json";
import assets from "./mocks/assets.json";
import dqChecks from "./mocks/dq-checks.json";
import evalEtr from "./mocks/eval-etr.json";
import evalOutage from "./mocks/eval-outage.json";
import evalSaa from "./mocks/eval-saa.json";
import feeds from "./mocks/feeds.json";
import modeLadder from "./mocks/mode-ladder.json";
import models from "./mocks/models.json";
import pipelineRuns from "./mocks/pipeline-runs.json";
import traces from "./mocks/traces.json";
import usage from "./mocks/usage.json";
import { KILL_ORDER, MODE_ORDER } from "./safety";
import type {
  AgentRun,
  Capabilities,
  CapabilityKey,
  ControlState,
  DegradedMode,
  KillLevel,
  RunStep,
} from "./types";

const fail = (status: number, code: string, message: string) =>
  HttpResponse.json({ error: { code, message } }, { status });

const evaluations: Record<string, unknown> = {
  "a2-excl-helene": evalOutage,
  "sgw-etr-a6": evalEtr,
  "saa-crew-plan": evalSaa,
};

const KILL_TRIGGER = new Set(["command", "operations", "water_operations", "executive"]);
const RESTORE_SIGN = new Set([
  "command",
  "compliance",
  "operations",
  "water_operations",
  "executive",
  "platform",
]);
const USAGE_VIEW = new Set(["platform", "command", "executive"]);
const RESTORE_MS = 15 * 60_000;
const KILL_FLOOR: Record<KillLevel, DegradedMode> = { K0: "M0", K1: "M0", K2: "M2", K3: "M3", K4: "M4" };

interface Pending {
  restore_id: string;
  from_level: KillLevel;
  to_level: KillLevel;
  requested_by: string;
  requested_function: string;
  requested_at: string;
  expires_at: string;
}

interface Control {
  kill_level: KillLevel;
  degraded_mode: DegradedMode;
  updated_by: string[];
  updated_at: string;
  pending: Pending | null;
}

const fresh = (): Control => ({
  kill_level: "K0",
  degraded_mode: "M0",
  updated_by: [],
  updated_at: "2026-11-19T22:00:02Z",
  pending: null,
});

let control = fresh();

/** Test and demo reset: back to K0 and M0 with no pending restore. */
export const resetControl = (): void => {
  control = fresh();
};

const rank = (m: DegradedMode) => MODE_ORDER.indexOf(m);
const klevel = (k: KillLevel) => KILL_ORDER.indexOf(k);

function capabilities(): Record<CapabilityKey, boolean> {
  const { kill_level: k, degraded_mode: m } = control;
  return {
    view_dashboards: klevel(k) < 4 && rank(m) < 4,
    create_proposals: klevel(k) < 3 && rank(m) < 4,
    approve_and_execute: klevel(k) < 1 && rank(m) < 4,
    agent_runs: klevel(k) < 2 && rank(m) < 2,
    llm_calls: klevel(k) < 2 && rank(m) < 2,
    free_form_plans: klevel(k) < 2 && rank(m) < 1,
    ingest_external: klevel(k) < 3 && rank(m) < 3,
    pipeline_runs: klevel(k) < 3 && rank(m) < 3,
    manual_workflow: true,
    crew_into_hazard_proposals: klevel(k) < 3 && rank(m) < 4,
  };
}

const state = (): ControlState => ({
  kill_level: control.kill_level,
  degraded_mode: control.degraded_mode,
  run_mode: "replay",
  updated_by: control.updated_by,
  updated_at: control.updated_at,
});

const capabilityView = (): Capabilities => ({
  kill_level: control.kill_level,
  degraded_mode: control.degraded_mode,
  control_readable: true,
  capabilities: capabilities(),
  active_signals: [],
  pending_restore:
    control.pending && Date.parse(control.pending.expires_at) > Date.now() ? control.pending : null,
  mode_ladder: modeLadder as Capabilities["mode_ladder"],
});

const me = () => (mockState.userId ? meFor(mockState.userId) : null);
const stoppedRuns = new Set<string>();
const withStops = (r: AgentRun): AgentRun => (stoppedRuns.has(r.run_id) ? { ...r, status: "cancelled" } : r);
export const resetStoppedRuns = () => stoppedRuns.clear();
const stepped = () => mockState.stepUpUntil > Date.now();
const signedOut = () => fail(401, "UNAUTHENTICATED", "sign in first");

async function postKill(request: Request) {
  const user = me();
  if (!user) return signedOut();
  const body = (await request.json()) as { kill_level: KillLevel; reason: string };
  if (!KILL_ORDER.includes(body.kill_level) || (body.reason ?? "").trim().length < 3)
    return fail(422, "VALIDATION_ERROR", "a level and a reason of at least 3 characters are required");
  if (!stepped()) return fail(403, "STEP_UP_REQUIRED", "re-enter your password to continue");
  const now = new Date();
  if (klevel(body.kill_level) > klevel(control.kill_level)) {
    if (!KILL_TRIGGER.has(String(user.function)))
      return fail(
        403,
        "KILL_TRIGGER_DENIED",
        "Only Command, Operations, Water operations and Executive can raise the stop level.",
      );
    control = {
      kill_level: body.kill_level,
      degraded_mode:
        rank(KILL_FLOOR[body.kill_level]) > rank(control.degraded_mode)
          ? KILL_FLOOR[body.kill_level]
          : control.degraded_mode,
      updated_by: [user.user_id],
      updated_at: now.toISOString(),
      pending: null,
    };
    return HttpResponse.json(state());
  }
  if (klevel(body.kill_level) === klevel(control.kill_level))
    return fail(409, "NO_CHANGE", "the stop level is already there");
  const pending = capabilityView().pending_restore;
  if (!pending) {
    if (!RESTORE_SIGN.has(String(user.function)))
      return fail(403, "RESTORE_DENIED", "Your team cannot sign a restore.");
    control.pending = {
      restore_id: "RST-0001",
      from_level: control.kill_level,
      to_level: body.kill_level,
      requested_by: user.user_id,
      requested_function: String(user.function),
      requested_at: now.toISOString(),
      expires_at: new Date(now.getTime() + RESTORE_MS).toISOString(),
    };
    return HttpResponse.json(state(), {
      status: 202,
      headers: { "X-SGW-Restore": "pending; id=RST-0001; awaiting=any other function" },
    });
  }
  if (String(user.function) === pending.requested_function)
    return fail(403, "SAME_FUNCTION", "A different team must sign this restore.");
  if (body.kill_level !== pending.to_level)
    return fail(409, "RESTORE_LEVEL_MISMATCH", "sign the level that was requested");
  const mode =
    control.degraded_mode === KILL_FLOOR[control.kill_level]
      ? KILL_FLOOR[pending.to_level]
      : control.degraded_mode;
  control = {
    ...control,
    kill_level: pending.to_level,
    degraded_mode: mode,
    updated_by: [pending.requested_by, user.user_id],
    updated_at: now.toISOString(),
    pending: null,
  };
  return HttpResponse.json(state());
}

async function postMode(request: Request) {
  const user = me();
  if (!user) return signedOut();
  const body = (await request.json()) as { degraded_mode: DegradedMode; reason: string };
  if (!MODE_ORDER.includes(body.degraded_mode) || (body.reason ?? "").trim().length < 3)
    return fail(422, "VALIDATION_ERROR", "a mode and a reason of at least 3 characters are required");
  if (!stepped()) return fail(403, "STEP_UP_REQUIRED", "re-enter your password to continue");
  const lowering = rank(body.degraded_mode) < rank(control.degraded_mode);
  if (lowering && String(user.function) !== "command")
    return fail(403, "MODE_LOWER_DENIED", "Only Command can lower the operating mode.");
  if (rank(body.degraded_mode) < rank(KILL_FLOOR[control.kill_level]))
    return fail(409, "MODE_BELOW_FLOOR", "The stop level keeps the mode at or above its floor.");
  control = {
    ...control,
    degraded_mode: body.degraded_mode,
    updated_by: [user.user_id],
    updated_at: new Date().toISOString(),
  };
  return HttpResponse.json(state());
}

export const handlers = [
  http.get("/api/feeds/health", () => (me() ? HttpResponse.json(feeds) : signedOut())),
  http.get("/api/pipeline/assets", () => (me() ? HttpResponse.json(assets) : signedOut())),
  http.get("/api/pipeline/runs", () => (me() ? HttpResponse.json(pipelineRuns) : signedOut())),
  http.post("/api/pipeline/assets/:name/run", ({ params }) => {
    const user = me();
    if (!user) return signedOut();
    if (!["data", "platform", "command", "operations"].includes(String(user.function)))
      return fail(403, "PIPELINE_RUN_DENIED", "pipeline runs are started by the data and platform teams");
    const at = new Date().toISOString();
    return HttpResponse.json(
      {
        run_id: "PRUN-MOCK",
        asset: String(params.name),
        status: "success",
        started_at: at,
        finished_at: at,
        rows_in: 0,
        rows_out: 0,
        rows_quarantined: 0,
        error: null,
      },
      { status: 202 },
    );
  }),
  http.get("/api/dq/checks", () => (me() ? HttpResponse.json(dqChecks) : signedOut())),
  http.get("/api/models", () => (me() ? HttpResponse.json(models) : signedOut())),
  http.get("/api/models/:name/evaluation", ({ params }) => {
    const found = evaluations[String(params.name)];
    return found ? HttpResponse.json(found as Record<string, unknown>) : undefined;
  }),
  http.get("/api/admin/ai-config", () => {
    const user = me();
    if (!user) return signedOut();
    return user.function === "platform"
      ? HttpResponse.json(aiConfig)
      : fail(403, "ADMIN_ONLY", "AI configuration is shown to platform administrators");
  }),
  http.get("/api/llm/usage", () => {
    const user = me();
    if (!user) return signedOut();
    return USAGE_VIEW.has(String(user.function))
      ? HttpResponse.json(usage)
      : fail(403, "USAGE_DENIED", "LLM usage is shown to platform, command and executive");
  }),
  http.get("/api/runs", () =>
    me() ? HttpResponse.json((agentRuns as AgentRun[]).map(withStops).map(toLiveRun)) : signedOut(),
  ),
  http.get("/api/runs/:id", ({ params }) => {
    if (!me()) return signedOut();
    const run = (agentRuns as AgentRun[]).find((r) => r.run_id === params.id);
    return run
      ? HttpResponse.json({
          run: toLiveRun(run),
          steps: ((traces as unknown as Record<string, RunStep[]>)[run.run_id] ?? []).map(toLiveStep),
        })
      : fail(404, "NOT_FOUND", "unknown run");
  }),
  http.post("/api/runs/:id/cancel", async ({ params, request }) => {
    const user = me();
    if (!user) return signedOut();
    if (user.function !== "platform" && user.function !== "data")
      return fail(403, "RUN_CANCEL_DENIED", "agent runs are cancelled by platform or data");
    const body = (await request.json()) as { reason?: string };
    if ((body.reason ?? "").trim().length < 3) return fail(422, "VALIDATION_ERROR", "a reason is required");
    const run = (agentRuns as AgentRun[]).map(withStops).find((r) => r.run_id === params.id);
    if (!run) return fail(404, "RUN_NOT_FOUND", "run not found");
    if (run.status !== "running" && run.status !== "waiting_approval")
      return fail(409, "RUN_NOT_ACTIVE", "only a running or paused run can be cancelled");
    stoppedRuns.add(run.run_id);
    return HttpResponse.json(toLiveRun(withStops(run)));
  }),
  http.get("/api/control/capabilities", () => (me() ? HttpResponse.json(capabilityView()) : signedOut())),
  http.get("/api/control/kill", () => (me() ? HttpResponse.json(state()) : signedOut())),
  http.get("/api/control/mode", () => (me() ? HttpResponse.json(state()) : signedOut())),
  http.post("/api/control/kill", ({ request }) => postKill(request)),
  http.post("/api/control/mode", ({ request }) => postMode(request)),
];
