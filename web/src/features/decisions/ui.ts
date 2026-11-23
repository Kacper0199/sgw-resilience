import { FUNCTION_LABEL, PERSONAS } from "@/auth/personas";
import type { components } from "@/contracts/api.gen";
import type { ApprovalFunction, NoRegretVerdict, UiSeverity } from "@/contracts/vocab.gen";
import type { ProposalCard, ProposalSummary } from "@/lib/api";
import { OPEN_STATES } from "./severity";

export type UiFields = Pick<ProposalSummary, "severity" | "proposed_by" | "owner_function">;

export const DOMAIN_LABEL = { electric: "Power", water: "Water" } as const;

export const TIMING_LABEL: Record<NoRegretVerdict, string> = {
  act_now: "Act now",
  decide_now: "Before next advisory",
  wait_for_next_advisory: "Can wait",
  "n/a": "By the deadline",
};

/** After the final advisory no next advisory exists: Timing names the deadline instead. */
export const TIMING_LABEL_AFTER_ADVISORIES: Record<NoRegretVerdict, string> = {
  ...TIMING_LABEL,
  decide_now: "By the deadline",
};

export const timingLabels = (advisoriesOver: boolean): Record<NoRegretVerdict, string> =>
  advisoriesOver ? TIMING_LABEL_AFTER_ADVISORIES : TIMING_LABEL;

/** The Timing word: act-or-wait advice only. Once the advisories are over, advice that waited on the next
 * advisory has nothing left to say, and a decision without advice has none: both read nothing, because the
 * time to the deadline is already beside it. */
export function timingText(verdict: NoRegretVerdict, phase: { advisoriesOver: boolean }): string | null {
  const advisoryBound = verdict === "decide_now" || verdict === "wait_for_next_advisory";
  if (verdict === "n/a" || (phase.advisoriesOver && advisoryBound)) return null;
  return TIMING_LABEL[verdict];
}

export type DecisionOutcome = NonNullable<ProposalSummary["outcome"]>;

export const OUTCOME_LABEL: Record<DecisionOutcome, string> = {
  on_time: "On time",
  late: "Late",
  missed: "Missed",
};

const CLOSED_STATE_LABEL: Partial<Record<ProposalSummary["state"], string>> = {
  approved: "Decided",
  executed: "Decided",
  rejected: "Sent back",
  withdrawn: "Withdrawn",
  expired: "Missed",
  draft: "Draft",
};

/** What became of a closed decision: the server's outcome (on time, late, missed), else its state. */
export const closedLabel = (p: Pick<ProposalSummary, "state" | "outcome">): string =>
  p.outcome ? OUTCOME_LABEL[p.outcome] : (CLOSED_STATE_LABEL[p.state] ?? "Closed");

const OUTCOME_LEVEL: Record<DecisionOutcome, UiSeverity> = {
  on_time: "normal",
  late: "elevated",
  missed: "critical",
};

/** The status mark of a decision: severity while it waits on signers, else its outcome or state, so a signed
 * decision never changes level with the state of what it acted on. */
export function decisionStatus(p: Pick<ProposalSummary, "state" | "outcome" | "severity">): {
  level: UiSeverity;
  label: string | undefined;
} {
  if (OPEN_STATES.has(p.state)) return { level: severityOf(p), label: undefined };
  return { level: p.outcome ? OUTCOME_LEVEL[p.outcome] : "advisory", label: closedLabel(p) };
}

type CaseChainStep = components["schemas"]["CaseChainStep"];

/** The linked sequence of a decision from its case (more than one step), or undefined when it stands alone. */
export const caseChainOf = (card: ProposalCard): readonly CaseChainStep[] | undefined => {
  const chain = card.case.chain;
  return chain && chain.length > 1 ? chain : undefined;
};

export const timingOf = (card: ProposalCard): NoRegretVerdict =>
  card.case.timing ?? card.case.no_regret_verdict;

/** Why Timing is inherited or not available, as one sentence; null when the decision has its own. */
export const timingReasonOf = (card: ProposalCard): string | null => card.case.timing_reason ?? null;

/** The line under Timing: how widely the advice holds, or the decision an inherited Timing follows. */
export function timingLineOf(card: ProposalCard, agreement: string | null | undefined): string | undefined {
  if (agreement) return `Holds up in ${agreement}`;
  if (timingOf(card) === "n/a" || !timingReasonOf(card)) return undefined;
  const reason = timingReasonOf(card) ?? "";
  const anchor = /“(.+?)”/.exec(reason)?.[1];
  const name = anchor ? shortDecisionName(anchor) : "the linked decision";
  return reason.startsWith("Needed before") ? `Ahead of ${name}` : `Follows ${name}`;
}

const FUNCTION_INITIALS: Record<ApprovalFunction, string> = {
  command: "IC",
  operations: "OP",
  planning: "PL",
  logistics: "LG",
  water_operations: "WO",
  compliance: "CP",
  executive: "EX",
  audit: "AU",
  platform: "PF",
  data: "DA",
  communications: "CM",
};

export const functionInitials = (fn: ApprovalFunction): string => FUNCTION_INITIALS[fn];

/** Severity comes from the API only; a payload without it reads as unknown, never as a value the browser worked out. */
export const severityOf = (p: Partial<UiFields>): UiSeverity => p.severity ?? "unknown_stale";

const personInitials = (name: string): string =>
  name
    .split(/[\s,]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");

export interface Owner {
  fn: ApprovalFunction | null;
  initials: string;
  label: string;
}

/** Owner: the initials of the person who proposed it, else the owning function (a system proposal has no person). */
export function ownerOf(p: Partial<UiFields> & { functions_required: ApprovalFunction[] }): Owner {
  const fn = p.owner_function !== undefined ? p.owner_function : (p.functions_required[0] ?? null);
  const label = fn ? FUNCTION_LABEL[fn] : "System";
  const who = p.proposed_by;
  if (who?.initiator_kind === "person") return { fn, initials: personInitials(who.display_name), label };
  return { fn, initials: fn ? functionInitials(fn) : "SY", label };
}

export function proposerLine(p: Partial<UiFields>): string | null {
  const who = p.proposed_by;
  if (!who) return null;
  if (who.initiator_kind === "person") return who.display_name;
  if (who.initiator_kind === "agent" && !who.user_id.startsWith("system:"))
    return `${who.display_name} (AI draft)`;
  return who.display_name.startsWith("SGW rule")
    ? "SGW rules (automatic)"
    : `${who.display_name} (automatic)`;
}

export const personName = (userId: string): string =>
  PERSONAS.find((p) => p.user_id === userId)?.title ?? userId;

const LEADING_VERB =
  /^(?:hook up|dispatch|hold|pre-position|secure|issue|send|publish|request|approve|open|run|confirm|clear|renew|top up|stage|raise)\s+(?:the\s+)?/i;

/** A decision title without its verb, for sentences that name another decision: "Hook up the portable generator at PS-17" reads "PS-17 portable generator". */
export function shortDecisionName(title: string): string {
  const noun = title.replace(LEADING_VERB, "");
  const placed = /^(.+?)\s+(?:at|to|for)\s+(\S+)$/.exec(noun);
  const name = placed ? `${placed[2]} ${placed[1]}` : noun;
  return name.length > 36 ? `${name.slice(0, 35).trimEnd()}…` : name;
}
