import type { NoRegretVerdict } from "@/contracts/vocab.gen";
import type { ProposalCard } from "@/lib/api";
import { plainIds } from "@/lib/names";
import { formatET } from "@/lib/time";
import { timingOf } from "./ui";

export interface Why {
  verdictLabel: string | null;
  action: string | null;
  reasons: string[];
  limit: string | null;
  agreement: string | null;
}

const VERDICT_LINE: Record<NoRegretVerdict, { label: string | null; action: string | null }> = {
  act_now: { label: "Act now", action: "act now" },
  decide_now: { label: "Before next advisory", action: "decide before the next advisory" },
  wait_for_next_advisory: { label: "Can wait", action: "wait for the next advisory" },
  "n/a": { label: null, action: null },
};

const sentences = (text: string): string[] =>
  text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter((s) => s && !/^synthetic data\.?$/i.test(s));

const AFTER_ADVISORIES: Partial<Record<NoRegretVerdict, { label: string; action: string }>> = {
  decide_now: { label: "By the deadline", action: "decide by the deadline" },
  wait_for_next_advisory: { label: "Can wait", action: "wait until closer to the deadline" },
};

/** Verdict, at most three reasons, one limit and the share of scenarios that agree (a percentage: the payload carries no member count); all from the card, nothing invented. After the final advisory no advisory can move the deadline. */
export function buildWhy(card: ProposalCard, advisoriesOver = false): Why {
  const verdict = timingOf(card);
  const { label, action } = (advisoriesOver && AFTER_ADVISORIES[verdict]) || VERDICT_LINE[verdict];
  const next = advisoriesOver ? null : card.case.next_advisory_utc;
  const share = card.case.no_regret_share_ppm;
  const agreeing = share === null || share === undefined ? null : Math.round(share / 10_000);
  return {
    verdictLabel: label,
    action,
    reasons: [...(card.case.timing_basis ? [card.case.timing_basis] : []), ...sentences(card.rationale)]
      .map(plainIds)
      .slice(0, 3),
    limit: next ? `The next advisory (${formatET(next)}) may move this deadline.` : null,
    agreement: agreeing === null ? null : `${agreeing}% of cases`,
  };
}
