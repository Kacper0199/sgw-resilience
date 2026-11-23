import { useState } from "react";
import { FUNCTION_LABEL } from "@/auth/personas";
import { useMe } from "@/auth/useSession";
import { Button } from "@/components/ui/button";
import { useCapabilities } from "@/features/health/useHealth";
import type { ProposalCard } from "@/lib/api";
import { SignDialog } from "./SignDialog";
import { OPEN_STATES } from "./severity";
import { type SignBlock, signBlock } from "./useQueue";
import type { SignDecision } from "./useSign";

function reason(block: Exclude<SignBlock, null>, fn: string, mine: boolean): string {
  if (block === "not_required") return `${fn} is not one of the teams that sign this decision.`;
  if (block === "already_signed") return mine ? "You signed." : `${fn} has already signed.`;
  return "This decision is closed.";
}

/** Sign as <team> (the one primary), Send back, and Approve alone… as red text. A disabled Sign says why, in place. */
export function ApprovalActions({ card, now }: { card: ProposalCard; now?: string }) {
  const me = useMe().data;
  const [dialog, setDialog] = useState<SignDecision | null>(null);
  const paused = useCapabilities().data?.capabilities.approve_and_execute === false;
  if (!me) return null;
  const block = signBlock(me, card);
  const fn = FUNCTION_LABEL[me.function];
  const others = card.functions_required
    .filter(
      (f) => f !== me.function && !card.approvals.some((a) => a.function === f && a.decision !== "reject"),
    )
    .map((f) => FUNCTION_LABEL[f]);
  const canApproveAlone =
    me.function === "command" &&
    OPEN_STATES.has(card.state) &&
    card.functions_required.length > 1 &&
    !card.break_glass;
  const mine = card.approvals.some((a) => a.approver_id === me.user_id && a.decision !== "reject");
  if (block && !dialog) return <p className="m-0 text-[13px] text-muted">{reason(block, fn, mine)}</p>;
  if (paused && !dialog)
    return (
      <p className="m-0 text-[13px] text-ink-2" data-testid="sign-paused">
        Signing is paused while the stop level is raised. See System health.
      </p>
    );
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" disabled={block !== null} onClick={() => setDialog("approve")}>
          Sign as {fn}
        </Button>
        <Button disabled={block !== null} onClick={() => setDialog("reject")}>
          Send back
        </Button>
        {canApproveAlone && (
          <Button
            variant="ghost"
            className="ml-auto text-crit hover:bg-crit-soft"
            onClick={() => setDialog("break_glass")}
          >
            Approve alone…
          </Button>
        )}
      </div>
      <p className="m-0 text-[13px] text-ink-2" data-testid="sign-line">
        You sign as {fn}, version {card.proposal_version}.
        {others.length > 0 && ` ${others.join(" and ")} also sign${others.length === 1 ? "s" : ""}.`}
      </p>
      {dialog && (
        <SignDialog
          card={card}
          decision={dialog}
          open
          onOpenChange={(o) => !o && setDialog(null)}
          now={now}
          onApproveAlone={canApproveAlone ? () => setDialog("break_glass") : undefined}
        />
      )}
    </div>
  );
}
