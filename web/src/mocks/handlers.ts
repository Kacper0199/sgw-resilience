import { delay, HttpResponse, http, type RequestHandler } from "msw";
import { handlers as generated } from "@/contracts/msw.gen";
import {
  type Advisory,
  advanceStory,
  auditFor,
  ENVELOPE_BOUNDS,
  policyParams,
  startStory,
} from "@/features/decisions/mocks/story";
import type { ApprovalRequest, BreakGlassRequest, ProposalCard } from "@/lib/api";
import { assets, freshCards, MOCK_NOW, meFor, regions, scenario, toSummary, toWaterfall } from "./fixtures";

interface FeatureMock {
  handlers?: RequestHandler[];
  decorateCards?: (cards: ProposalCard[]) => ProposalCard[];
}

/** A feature adds its own endpoints and extra queue cards in `features/<name>/mocks.ts`; nothing else is edited. */
const featureMocks = Object.values(import.meta.glob<FeatureMock>("../features/*/mocks.ts", { eager: true }));
const featureHandlers = featureMocks.flatMap((m) => m.handlers ?? []);
const seedCards = (): ProposalCard[] =>
  featureMocks.reduce((cards, m) => m.decorateCards?.(cards) ?? cards, freshCards());

const error = (status: number, code: string, message: string) =>
  HttpResponse.json({ error: { code, message } }, { status });

interface MockState {
  userId: string | null;
  stepUpUntil: number;
  cards: ProposalCard[];
}

const STORED = "sgw.mock.user";
/** `sessionStorage["sgw.mock.after_landfall"] = "1"`: the mock clock reads as after landfall (damage photos shown). */
const AFTER_LANDFALL_KEY = "sgw.mock.after_landfall";
const stored = () => (typeof sessionStorage === "undefined" ? null : sessionStorage.getItem(STORED));

export const mockState: MockState = { userId: stored(), stepUpUntil: 0, cards: seedCards() };

function remember(userId: string | null) {
  mockState.userId = userId;
  if (typeof sessionStorage === "undefined") return;
  if (userId) sessionStorage.setItem(STORED, userId);
  else sessionStorage.removeItem(STORED);
}

export function resetMock(): void {
  remember(null);
  mockState.stepUpUntil = 0;
  mockState.cards = seedCards();
  scenario.scenario_time = MOCK_NOW;
  scenario.speed = 0;
}

export const runStory = {
  start: (advisory: Advisory) => startStory(advisory, { cards: mockState.cards, scenario, emit: emitLedger }),
  advance: (advisory: Advisory) =>
    advanceStory(advisory, { cards: mockState.cards, scenario, emit: emitLedger }),
};

const sinks = new Set<(chunk: Uint8Array) => void>();
let pushedSeq = 1000;

/** Announces a ledger event on every open ops stream, the way the server does. */
export function emitLedger(eventType: string, payload: object, scenarioTime: string): void {
  const seq = ++pushedSeq;
  const resync = eventType === "resync";
  const frame = {
    v: 1,
    type: resync ? "resync" : "ledger",
    seq,
    ledger_seq: resync ? null : seq,
    run_id: null,
    ns: [],
    ts: "2026-11-20T00:00:00Z",
    scenario_time: scenarioTime,
    run_mode: "replay",
    classification: "C1",
    payload: resync ? payload : { event_id: `mock-${seq}`, event_type: eventType, payload },
  };
  const chunk = new TextEncoder().encode(
    `id: ops.1.${seq}\nevent: ${resync ? "resync" : "ledger"}\ndata: ${JSON.stringify(frame)}\n\n`,
  );
  for (const sink of sinks) sink(chunk);
}

declare global {
  interface Window {
    __sgwStory?: { start: (advisory: Advisory) => void; advance: (advisory: Advisory) => void };
  }
}

if (typeof window !== "undefined") {
  window.__sgwStory = runStory;
}

const currentMe = () => {
  const me = mockState.userId ? meFor(mockState.userId) : null;
  if (!me) return null;
  return {
    ...me,
    step_up_valid_until:
      mockState.stepUpUntil > Date.now() ? new Date(mockState.stepUpUntil).toISOString() : null,
  };
};

const STEP_UP_MS = 300_000;

function opsStream(): Response {
  const enc = new TextEncoder();
  const frame = (id: string, event: string, payload: object, seq: number) =>
    enc.encode(
      `id: ${id}\nevent: ${event}\ndata: ${JSON.stringify({
        v: 1,
        type: event,
        seq,
        ledger_seq: event === "ledger" ? seq : null,
        run_id: null,
        ns: [],
        ts: "2026-11-20T00:00:00Z",
        scenario_time: scenario.scenario_time,
        run_mode: "replay",
        classification: "C1",
        payload,
      })}\n\n`,
    );
  let sink: ((chunk: Uint8Array) => void) | null = null;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      sink = (chunk: Uint8Array) => controller.enqueue(chunk);
      sinks.add(sink);
      controller.enqueue(
        frame(
          "ops.1.0",
          "heartbeat",
          { degraded_mode: "M0", head_ledger_seq: 0, kill_level: "K0", server_time: "2026-11-20T00:00:00Z" },
          0,
        ),
      );
      controller.enqueue(
        frame(
          "ops.1.1",
          "ledger",
          {
            event_id: "mock-1",
            event_type: "ScenarioClockChanged",
            payload: { bookmark: "H0-24", scenario_time_utc: scenario.scenario_time, speed: scenario.speed },
          },
          1,
        ),
      );
    },
    cancel() {
      if (sink) sinks.delete(sink);
    },
  });
  return new HttpResponse(stream, {
    headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
  });
}

export const handlers = [
  ...featureHandlers,
  http.get("/api/auth/config", () => HttpResponse.json({ demo_mode: true, demo_password: "123" })),
  http.post("/api/auth/login", async ({ request }) => {
    const body = (await request.json()) as { user_id: string; password: string };
    const me = meFor(body.user_id);
    if (!me || !body.password) return error(401, "UNAUTHENTICATED", "user id or password did not match");
    remember(body.user_id);
    mockState.stepUpUntil = Date.now() + STEP_UP_MS;
    // biome-ignore lint/suspicious/noDocumentCookie: mock mode emulates the CSRF cookie the API sets at login
    document.cookie = "sgw_csrf=mock-csrf; path=/";
    return HttpResponse.json(currentMe());
  }),
  http.post("/api/auth/logout", () => {
    remember(null);
    // biome-ignore lint/suspicious/noDocumentCookie: mock mode clears the emulated CSRF cookie
    document.cookie = "sgw_csrf=; path=/; max-age=0";
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("/api/auth/step-up", async ({ request }) => {
    const body = (await request.json()) as { password: string };
    if (!mockState.userId) return error(401, "UNAUTHENTICATED", "sign in first");
    if (!body.password || body.password === "wrong")
      return error(401, "STEP_UP_FAILED", "password did not match");
    mockState.stepUpUntil = Date.now() + STEP_UP_MS;
    return HttpResponse.json(currentMe());
  }),
  http.get("/api/me", () => {
    const me = currentMe();
    return me ? HttpResponse.json(me) : error(401, "UNAUTHENTICATED", "sign in first");
  }),
  http.get("/api/scenario", () =>
    HttpResponse.json(
      typeof sessionStorage !== "undefined" && sessionStorage.getItem(AFTER_LANDFALL_KEY) === "1"
        ? { ...scenario, phases: [{ phase: "storm", label: "Storm", starts_utc: scenario.window_start }] }
        : scenario,
    ),
  ),
  http.post("/api/scenario", async ({ request }) => {
    const me = currentMe();
    if (!me) return error(401, "UNAUTHENTICATED", "sign in first");
    if (me.function !== "command" && me.function !== "operations" && !me.roles.includes("presenter"))
      return error(403, "SCENARIO_CONTROL_DENIED", "this role can read the scenario clock but not move it");
    const body = (await request.json()) as {
      action: string;
      scenario_time?: string;
      speed?: 0 | 1 | 60 | 900;
    };
    await delay(150);
    if (body.action === "pause") scenario.speed = 0;
    else if (body.action === "play") scenario.speed = 60;
    else if (body.action === "speed" && body.speed !== undefined) scenario.speed = body.speed;
    else if (body.action === "seek" && body.scenario_time) scenario.scenario_time = body.scenario_time;
    else return error(422, "INVALID_COMMAND", "unknown command");
    return HttpResponse.json(scenario);
  }),
  http.post("/api/demo/goto", async ({ request }) => {
    const me = currentMe();
    if (!me) return error(401, "UNAUTHENTICATED", "sign in first");
    if (me.function !== "command" && me.function !== "operations" && !me.roles.includes("presenter"))
      return error(403, "SCENARIO_CONTROL_DENIED", "this role can read the scenario clock but not move it");
    const { bookmark } = (await request.json()) as { bookmark: string };
    const moment = (scenario.jumps ?? []).find((j) => j.moment_id === bookmark);
    if (!moment) return error(404, "DEMO_MOMENT_NOT_FOUND", `no demo moment ${bookmark}`);
    await delay(300);
    scenario.scenario_time = moment.scenario_time;
    return HttpResponse.json({
      bookmark,
      title: moment.label,
      scenario_time: moment.scenario_time,
      seconds: 1.2,
    });
  }),
  http.get("/api/regions", () => HttpResponse.json(regions)),
  http.get("/api/assets", () => HttpResponse.json(assets)),
  http.get("/api/stream/ops", () => opsStream()),
  http.get("/api/audit", () => HttpResponse.json(auditFor(mockState.cards))),
  http.get("/api/policies", () => HttpResponse.json(policyParams())),
  http.get("/api/proposals", async () => {
    await delay(40);
    return mockState.userId
      ? HttpResponse.json(mockState.cards.map(toSummary))
      : error(401, "UNAUTHENTICATED", "sign in first");
  }),
  http.get("/api/proposals/:id/evidence", ({ params }) => {
    const card = mockState.cards.find((c) => c.proposal_id === params.id);
    return card
      ? HttpResponse.json(
          card.evidence_ids.map((id) => ({
            id,
            recorded: true,
            kind: "observation",
            title: id.startsWith("EV-HOSP") ? "Hospital storage level" : "Station pressure readings",
            source: "SCADA, synthetic",
            as_of_utc: null,
            model_version: null,
            classification: "C1",
            trust: "measured",
            withheld: false,
            run_id: null,
            graph: null,
          })),
        )
      : error(404, "NOT_FOUND", "unknown proposal");
  }),
  http.get("/api/proposals/:id/clock", ({ params }) => {
    const card = mockState.cards.find((c) => c.proposal_id === params.id);
    return card ? HttpResponse.json(toWaterfall(card)) : error(404, "NOT_FOUND", "unknown proposal");
  }),
  http.get("/api/proposals/:id", ({ params }) => {
    const card = mockState.cards.find((c) => c.proposal_id === params.id);
    return card ? HttpResponse.json(card) : error(404, "NOT_FOUND", "unknown proposal");
  }),
  http.post("/api/proposals/:id/approvals", async ({ params, request }) => {
    const card = mockState.cards.find((c) => c.proposal_id === params.id);
    const me = currentMe();
    if (!card || !me) return error(404, "NOT_FOUND", "unknown proposal");
    if (!me.step_up_valid_until) return error(403, "STEP_UP_REQUIRED", "re-enter your password to continue");
    const body = (await request.json()) as ApprovalRequest;
    if (body.proposal_version !== card.proposal_version || body.action_hash !== card.action_hash) {
      return HttpResponse.json(
        { current_version: card.proposal_version, current_action_hash: card.action_hash, changed_fields: [] },
        { status: 412 },
      );
    }
    if (!card.functions_required.includes(me.function)) {
      return error(403, "FUNCTION_NOT_REQUIRED", "your function is not required to sign this decision");
    }
    if (card.approvals.some((a) => a.function === me.function)) {
      return error(409, "ALREADY_SIGNED", "your function has already signed");
    }
    card.approvals.push({
      approver_id: me.user_id,
      function: me.function,
      decision: body.decision,
      at: scenario.scenario_time,
    });
    const remaining = card.functions_required.filter((f) => !card.approvals.some((a) => a.function === f));
    card.state = body.decision === "reject" ? "rejected" : remaining.length === 0 ? "approved" : "in_review";
    if (card.state === "approved" && card.action_type === "preposition_crews" && card.proposal_version > 1) {
      card.envelope = {
        envelope_id: "ENV-CREW-AIK-V2",
        proposal_id: card.proposal_id,
        bounds: ENVELOPE_BOUNDS,
        valid_until_utc: "2024-09-27T12:00:00Z",
      };
    }
    return HttpResponse.json({
      approval_id: `APR-${card.approvals.length}`,
      proposal_state: card.state,
      remaining_functions: remaining,
    });
  }),
  http.post("/api/proposals/:id/withdraw", async ({ params, request }) => {
    const card = mockState.cards.find((c) => c.proposal_id === params.id);
    const me = currentMe();
    if (!card || !me) return error(404, "NOT_FOUND", "unknown proposal");
    const body = (await request.json()) as { reason?: string };
    if ((body.reason ?? "").trim().length < 3) return error(422, "VALIDATION_ERROR", "a reason is required");
    if (card.proposed_by.user_id === me.user_id) {
      card.state = "withdrawn";
    } else {
      const own = card.approvals.findIndex((a) => a.approver_id === me.user_id && a.decision === "approve");
      if (own < 0 || card.state !== "in_review")
        return error(
          403,
          "NOT_ENTITLED",
          "only the proposer, or an approver for their own signature, may withdraw",
        );
      card.approvals.splice(own, 1);
      card.state = card.approvals.length ? "in_review" : "proposed";
    }
    return HttpResponse.json(toSummary(card));
  }),
  http.post("/api/proposals/:id/break-glass", async ({ params, request }) => {
    const card = mockState.cards.find((c) => c.proposal_id === params.id);
    const me = currentMe();
    if (!card || !me) return error(404, "NOT_FOUND", "unknown proposal");
    if (!me.step_up_valid_until) return error(403, "STEP_UP_REQUIRED", "re-enter your password to continue");
    if (me.function !== "command")
      return error(403, "FORBIDDEN", "only the Incident Commander can break glass");
    const body = (await request.json()) as BreakGlassRequest;
    if (body.proposal_version !== card.proposal_version || body.action_hash !== card.action_hash) {
      return HttpResponse.json(
        { current_version: card.proposal_version, current_action_hash: card.action_hash, changed_fields: [] },
        { status: 412 },
      );
    }
    const usedAt = scenario.scenario_time;
    card.approvals.push({
      approver_id: me.user_id,
      function: me.function,
      decision: "break_glass",
      at: usedAt,
    });
    card.state = "approved";
    card.break_glass = {
      proposal_id: card.proposal_id,
      ic_id: me.user_id,
      reason: body.reason,
      used_at_utc: usedAt,
      cosign_due_utc: new Date(Date.parse(usedAt) + 24 * 3_600_000).toISOString(),
      cosigned_by: null,
      cosigned_at_utc: null,
      flagged_for_after_action: true,
    };
    return HttpResponse.json(card);
  }),
  http.post("/api/proposals/:id/cosign", ({ params }) => {
    const card = mockState.cards.find((c) => c.proposal_id === params.id);
    const me = currentMe();
    if (!card?.break_glass || !me) return error(404, "NOT_FOUND", "no break-glass to co-sign");
    if (!me.step_up_valid_until) return error(403, "STEP_UP_REQUIRED", "re-enter your password to continue");
    card.break_glass.cosigned_by = me.user_id;
    card.break_glass.cosigned_at_utc = scenario.scenario_time;
    return HttpResponse.json({ proposal_id: card.proposal_id, overdue: false });
  }),
  ...generated,
];
