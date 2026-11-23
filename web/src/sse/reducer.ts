import type { QueryKey } from "@tanstack/react-query";
import type { WireFrame } from "@/contracts/wire.gen";

export type Connection = "idle" | "connecting" | "live" | "reconnecting" | "stale";

export interface OpsState {
  connection: Connection;
  lastEventId: string | null;
  headLedgerSeq: number | null;
  scenarioTime: string | null;
  speed: number | null;
  /** Wall-clock ms at which `scenarioTime` was observed, so the clock can run between frames. */
  anchorWallMs: number | null;
  killLevel: string | null;
  degradedMode: string | null;
  lastFrameWallMs: number | null;
  resyncs: number;
}

export const initialOpsState: OpsState = {
  connection: "idle",
  lastEventId: null,
  headLedgerSeq: null,
  scenarioTime: null,
  speed: null,
  anchorWallMs: null,
  killLevel: null,
  degradedMode: null,
  lastFrameWallMs: null,
  resyncs: 0,
};

export interface Effect {
  invalidate: QueryKey;
  /** Match only this exact key (the queue list), not the cards under it. */
  exact?: boolean;
  /** Match cards of this decision case. */
  caseId?: string;
  /** The server now reads another database (a loaded moment): drop the old one's cache. */
  newDatabase?: boolean;
}

const LIST: Effect = { invalidate: ["proposals"], exact: true };

/** Read models built from proposal states: the water register, the Briefing and the crew assignment targets. */
const DERIVED: Effect[] = [
  { invalidate: ["water"] },
  { invalidate: ["brief"] },
  { invalidate: ["crews", "targets"] },
];

const PROPOSAL_EVENTS = new Set([
  "ProposalCreated",
  "ProposalUpdated",
  "ApprovalRecorded",
  "DecisionApproved",
  "EnvelopeApproved",
]);

/** Ledger events that can add or close an item of the notification feed. */
const NOTIFY_EVENTS = new Set([
  ...PROPOSAL_EVENTS,
  "DecisionClockUpdated",
  "ScenarioClockChanged",
  "KillSwitchChanged",
  "ModeChanged",
  "CrewStatus",
  "EtrPublished",
]);

function effectsFor(eventType: string, inner: Record<string, unknown>): Effect[] {
  if (eventType === "ScenarioClockChanged") return [{ invalidate: ["scenario"] }];
  if (eventType === "RiskSnapshotPublished") return [{ invalidate: ["risk"] }];
  if (eventType === "CommitmentCreated") return [{ invalidate: ["commitments"] }];
  if (eventType === "DecisionClockUpdated") {
    const caseId = typeof inner.decision_case_id === "string" ? inner.decision_case_id : null;
    return caseId ? [LIST, { invalidate: ["proposals"], caseId }] : [{ invalidate: ["proposals"] }];
  }
  if (PROPOSAL_EVENTS.has(eventType)) {
    const id = typeof inner.proposal_id === "string" ? inner.proposal_id : null;
    return [
      ...(id ? [LIST, { invalidate: ["proposals", id] }] : [{ invalidate: ["proposals"] }]),
      ...DERIVED,
    ];
  }
  return [];
}

const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" ? v : null);

export interface Reduction {
  state: OpsState;
  effects: Effect[];
}

/** Pure: folds one K4 wire frame into the ops state and lists the query invalidations it causes. */
export function reduceFrame(
  state: OpsState,
  frame: WireFrame,
  eventId: string | undefined,
  wallNowMs: number,
): Reduction {
  const payload = (frame.payload ?? {}) as Record<string, unknown>;
  let next: OpsState = {
    ...state,
    connection: "live",
    lastEventId: eventId ?? state.lastEventId,
    lastFrameWallMs: wallNowMs,
  };
  const effects: Effect[] = [];

  const clockFrame = frame.type === "heartbeat" || frame.type === "resync";
  if (clockFrame && frame.scenario_time && frame.scenario_time !== state.scenarioTime) {
    next = { ...next, scenarioTime: frame.scenario_time, anchorWallMs: wallNowMs };
  }

  switch (frame.type) {
    case "heartbeat":
      next = {
        ...next,
        headLedgerSeq: num(payload.head_ledger_seq) ?? next.headLedgerSeq,
        killLevel: str(payload.kill_level) ?? next.killLevel,
        degradedMode: str(payload.degraded_mode) ?? next.degradedMode,
      };
      break;
    case "ledger": {
      if (frame.ledger_seq !== null) next = { ...next, headLedgerSeq: frame.ledger_seq };
      const eventType = str(payload.event_type) ?? "";
      const inner = (payload.payload ?? {}) as Record<string, unknown>;
      if (eventType === "ScenarioClockChanged") {
        next = {
          ...next,
          scenarioTime: str(inner.scenario_time_utc) ?? next.scenarioTime,
          speed: num(inner.speed) ?? next.speed,
          anchorWallMs: wallNowMs,
        };
      }
      effects.push(...effectsFor(eventType, inner));
      if (NOTIFY_EVENTS.has(eventType)) effects.push({ invalidate: ["notifications"] });
      break;
    }
    case "resync":
      next = { ...next, resyncs: state.resyncs + 1 };
      effects.push({ invalidate: [], newDatabase: payload.reason === "epoch_mismatch" });
      break;
    default:
      break;
  }
  return { state: next, effects };
}

export function scenarioNowMs(state: OpsState, wallNowMs: number, fallbackSpeed = 0): number | null {
  if (!state.scenarioTime || state.anchorWallMs === null) return null;
  const speed = state.speed ?? fallbackSpeed;
  return Date.parse(state.scenarioTime) + Math.max(0, wallNowMs - state.anchorWallMs) * speed;
}
