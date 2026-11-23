import { ShieldAlert } from "lucide-react";
import { useState } from "react";
import { FUNCTION_LABEL } from "@/auth/personas";
import { useMe } from "@/auth/useSession";

import { Button } from "@/components/ui/button";
import type { ProposalCard } from "@/lib/api";
import { formatRecorded } from "@/lib/time";
import { PaneSection } from "./PaneSection";
import { SignDialog } from "./SignDialog";
import { personName } from "./ui";

/** Shown after break-glass was used: who, why, and the co-sign still owed within the window. */
export function BreakGlassCard({ card }: { card: ProposalCard }) {
  const me = useMe().data;
  const [dialog, setDialog] = useState(false);
  const bg = card.break_glass;
  if (!bg) return null;
  const done = Boolean(bg.cosigned_by);
  const canCosign =
    !done &&
    me &&
    me.user_id !== bg.ic_id &&
    card.functions_required.includes(me.function) &&
    me.function !== "command";
  return (
    <PaneSection title="Emergency approval used" info="break_glass">
      <div className="flex flex-col gap-2 text-[13px]" data-testid="break-glass-card">
        <p className="m-0 flex items-start gap-2">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            {personName(bg.ic_id)} approved alone on{" "}
            <span className="tnum">{formatRecorded(bg.used_at_utc)}</span>.
          </span>
        </p>
        <p className="m-0">
          <span className="font-medium">Reason: </span>
          {bg.reason}
        </p>
        <p className="m-0 text-muted tnum">
          {done
            ? `Co-signed by ${personName(bg.cosigned_by as string)}${bg.cosigned_at_utc ? ` on ${formatRecorded(bg.cosigned_at_utc)}` : ""}.`
            : `A second team must co-sign by ${formatRecorded(bg.cosign_due_utc)}. Every emergency approval is reviewed later.`}
        </p>
        {canCosign && (
          <div>
            <Button size="sm" onClick={() => setDialog(true)}>
              Co-sign as {me ? FUNCTION_LABEL[me.function] : ""}
            </Button>
          </div>
        )}
        {dialog && (
          <SignDialog card={card} decision="cosign" open onOpenChange={(o) => !o && setDialog(false)} />
        )}
      </div>
    </PaneSection>
  );
}
