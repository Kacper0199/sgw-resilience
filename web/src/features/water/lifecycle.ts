import type { ProposalCard } from "@/lib/api";
import type { BwaAdvisory, NoticeStage, WaterZoneWithHistory } from "./types";

export const NOTICE_STEPS = [
  { key: "due", label: "Due" },
  { key: "issued", label: "Issued" },
  { key: "samples", label: "Samples" },
  { key: "lift", label: "Lift decision" },
  { key: "lifted", label: "Lifted" },
] as const;

export type NoticeStep = (typeof NOTICE_STEPS)[number]["key"];
export type StepState = "done" | "current" | "todo";

export interface ZoneNotice {
  zoneId: string;
  steps: { key: NoticeStep; label: string; state: StepState }[];
  current: NoticeStep;
  status: { level: "normal" | "advisory" | "elevated" | "severe"; label: string };
  /** The decision to act on now: the open lift, else the notice. */
  decision?: ProposalCard;
  dueUtc?: string;
  cleanSamples?: number;
  samplesNeeded?: number;
  waitingForSignature: boolean;
}

type Stage = NonNullable<NoticeStage>;

const RANK: Record<Stage, number> = { due: 0, issued: 1, samples: 2, lift_decision: 3, lifted: 4 };
const STEP_OF: Record<Stage, NoticeStep> = {
  due: "due",
  issued: "samples",
  samples: "samples",
  lift_decision: "lift",
  lifted: "lifted",
};

const indexOf = (key: NoticeStep): number => NOTICE_STEPS.findIndex((s) => s.key === key);

function build(current: NoticeStep, finished: boolean) {
  const at = indexOf(current);
  return NOTICE_STEPS.map((s, i) => ({
    ...s,
    state: finished || i < at ? ("done" as const) : i === at ? ("current" as const) : ("todo" as const),
  }));
}

/** The zone's register row furthest along the lifecycle; rows without a stage have no notice due. */
function furthest(advisories: BwaAdvisory[], zoneId: string): (BwaAdvisory & { stage: Stage }) | undefined {
  return advisories
    .filter((a): a is BwaAdvisory & { stage: Stage } => a.zone_id === zoneId && !!a.stage)
    .sort((a, b) => RANK[b.stage] - RANK[a.stage])[0];
}

/**
 * Where a zone stands in the boil-water notice lifecycle, as `GET /api/water/advisories` reports it: due, issued,
 * samples (clean lab samples coming in), lift decision, lifted. The proposal cards only supply the decision to link
 * and its deadline. `undefined` when the register has no notice due for the zone.
 */
export function noticeLifecycle(
  zone: Pick<WaterZoneWithHistory, "zone_id">,
  advisories: BwaAdvisory[],
  cards: ProposalCard[],
): ZoneNotice | undefined {
  const row = furthest(advisories, zone.zone_id);
  if (!row) return undefined;
  const byId = (id: string | null | undefined) => (id ? cards.find((c) => c.proposal_id === id) : undefined);
  const notice = byId(row.proposal_id);
  const lift = byId(row.lift_proposal_id);
  const samples = {
    cleanSamples: row.clean_samples ?? undefined,
    samplesNeeded: row.samples_needed ?? undefined,
  };
  const base = { zoneId: zone.zone_id, current: STEP_OF[row.stage], ...samples };
  switch (row.stage) {
    case "lifted":
      return {
        ...base,
        steps: build("lifted", true),
        status: { level: "normal", label: "Lifted" },
        waitingForSignature: false,
      };
    case "lift_decision":
      return {
        ...base,
        steps: build("lift", false),
        status: { level: "elevated", label: "Lift waiting for sign-off" },
        decision: lift,
        dueUtc: lift?.effective_decide_by_utc,
        waitingForSignature: true,
      };
    case "issued":
    case "samples":
      return {
        ...base,
        steps: build("samples", false),
        status: { level: "advisory", label: "Waiting for clean samples" },
        decision: notice,
        waitingForSignature: false,
      };
    default: {
      const waiting = row.status === "proposed";
      return {
        ...base,
        steps: build("due", false),
        status: waiting
          ? { level: "elevated", label: "Waiting for sign-off" }
          : { level: "advisory", label: "Not proposed yet" },
        decision: waiting ? notice : undefined,
        dueUtc: (waiting ? notice?.effective_decide_by_utc : undefined) ?? row.due_utc ?? undefined,
        waitingForSignature: waiting,
      };
    }
  }
}

/** Notices with a decision someone can sign now: the KPI "Notice waiting for sign-off". */
export const waitingForSignOff = (notices: ZoneNotice[]): ZoneNotice[] =>
  notices.filter((n) => n.waitingForSignature);

const URGENCY: Record<NoticeStep, number> = { due: 0, lift: 1, issued: 2, samples: 3, lifted: 4 };

/** Zones that need a signature come first (earliest deadline), then those waiting on samples, lifted last. */
export function noticesInOrder(notices: ZoneNotice[]): ZoneNotice[] {
  const due = (n: ZoneNotice) => (n.dueUtc ? Date.parse(n.dueUtc) : Number.MAX_SAFE_INTEGER);
  return [...notices].sort((a, b) => URGENCY[a.current] - URGENCY[b.current] || due(a) - due(b));
}
