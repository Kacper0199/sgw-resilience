import type { ProposalSummary } from "@/lib/api";
import { ELEVATED_WITHIN_MINUTES, SOON_MINUTES } from "@/lib/thresholds";
import { minutesUntil } from "@/lib/time";

export const OPEN_STATES: ReadonlySet<ProposalSummary["state"]> = new Set([
  "proposed",
  "in_review",
  "escalated",
]);

/** Settled one way or another: decided, missed, sent back or withdrawn (a draft is not yet open). */
export const isClosed = (state: ProposalSummary["state"]): boolean =>
  !OPEN_STATES.has(state) && state !== "draft";

/** Still to be done: waiting on signers, or a one-person draft not yet confirmed. */
export const isPending = (state: ProposalSummary["state"]): boolean =>
  OPEN_STATES.has(state) || state === "draft";

export type Bucket = "overdue" | "hour" | "six_hours" | "later" | "closed";

export const BUCKET_LABEL: Record<Bucket, string> = {
  overdue: "Overdue",
  hour: "Next hour",
  six_hours: "Next 6 hours",
  later: "Over 6 hours",
  closed: "Closed",
};

export const BUCKET_ORDER: readonly Bucket[] = ["overdue", "hour", "six_hours", "later", "closed"];

export function bucketOf(p: ProposalSummary, now: string): Bucket {
  if (!isPending(p.state)) return "closed";
  const min = minutesUntil(p.effective_decide_by_utc, now);
  if (min < 0) return "overdue";
  if (min < SOON_MINUTES) return "hour";
  return min < ELEVATED_WITHIN_MINUTES ? "six_hours" : "later";
}
