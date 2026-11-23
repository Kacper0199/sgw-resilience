import { MessageSquareText, RotateCcw } from "lucide-react";
import { InfoTip, SectionCard } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { PlanChecklist } from "./PlanChecklist";
import { StepLog } from "./StepLog";
import type { RunView } from "./types";

interface Props {
  run: RunView;
  onRunAgain?: (run: RunView) => void;
  onOpenConversation?: (run: RunView) => void;
}

export function RunDetail({ run, onRunAgain, onOpenConversation }: Props) {
  return (
    <div className="flex flex-col gap-3" data-testid="run-detail">
      <div>
        <h3 className="m-0 text-[14px] leading-snug font-semibold break-words">
          {run.question || "Untitled question"}
        </h3>
        {run.error && (
          <p role="alert" className="m-0 mt-1.5 text-[13px] text-error">
            {run.error}
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {onRunAgain && run.graph === "copilot" && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => onRunAgain(run)}
            disabled={run.status === "running"}
          >
            <RotateCcw aria-hidden />
            Ask again
          </Button>
        )}
        {onOpenConversation && (
          <Button size="sm" variant="ghost" onClick={() => onOpenConversation(run)}>
            <MessageSquareText aria-hidden />
            Open chat
          </Button>
        )}
      </div>
      <div className="flex flex-col gap-3 border-t border-hair pt-3">
        <p className="m-0 flex items-center gap-1 text-[13px] font-semibold">
          Steps
          <InfoTip term="how_i_got_this" />
        </p>
        <SectionCard title="Plan">
          <PlanChecklist run={run} />
        </SectionCard>
        <SectionCard title="Step details">
          <StepLog run={run} />
        </SectionCard>
      </div>
    </div>
  );
}
