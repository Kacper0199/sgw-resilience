import { ClockText, type Status, StatusIndicator } from "@/components/sgw";
import type { ProposalCard } from "@/lib/api";
import { plainIds } from "@/lib/names";
import { formatEtZ, minutesUntil } from "@/lib/time";
import { OPEN_STATES } from "./severity";
import { closedLabel } from "./ui";

export function clockStatus(
  card: Pick<ProposalCard, "state" | "approvals" | "effective_decide_by_utc" | "outcome">,
  now: string,
): { status: Status; label: string } {
  if (card.state === "expired" || card.outcome === "late" || card.outcome === "missed") {
    return { status: "missed", label: closedLabel(card) };
  }
  if (card.state === "approved" || card.state === "executed")
    return { status: "met", label: closedLabel(card) };
  if (!OPEN_STATES.has(card.state)) return { status: "idle", label: closedLabel(card) };
  if (minutesUntil(card.effective_decide_by_utc, now) < 0) return { status: "missed", label: "Missed" };
  if (card.approvals.some((a) => a.decision !== "reject")) {
    return { status: "waiting_approval", label: "Waiting for sign-off" };
  }
  return { status: "running", label: "Running" };
}

/** The clock of one decision: relative and absolute time, a state glyph, and what happens if it is missed. */
export function DecisionClock({ card, now }: { card: ProposalCard; now: string }) {
  const { status, label } = clockStatus(card, now);
  const clock = card.case.clock;
  const closed = !OPEN_STATES.has(card.state);
  return (
    <div className="flex flex-col gap-0.5" data-testid="decision-clock">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[14px]">
        {closed ? (
          <span className="tnum text-muted">Was due {formatEtZ(card.effective_decide_by_utc)}</span>
        ) : (
          <ClockText at={card.effective_decide_by_utc} now={now} />
        )}
        <StatusIndicator status={status} label={label} />
      </div>
      <p className="m-0 text-[13px] text-muted">
        {plainIds(clock.if_late).replace(/\.$/, "")}; impact starts {formatEtZ(clock.consequence_utc)}
      </p>
    </div>
  );
}
