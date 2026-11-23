import { ListChecks } from "lucide-react";
import { EmptyState } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { RunDetail } from "../agent-panel/RunDetail";
import { RunsTable } from "../agent-panel/RunsTable";
import type { RunView } from "../agent-panel/types";

interface Props {
  runs: RunView[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onRunAgain: (run: RunView) => void;
  onOpenConversation: (run: RunView) => void;
  onBack: () => void;
}

/** Activity: every question with the steps behind its answer. Reached from the history panel or an answer. */
export function RunsPane({ runs, selectedId, onSelect, onRunAgain, onOpenConversation, onBack }: Props) {
  const selected = runs.find((r) => r.runId === selectedId) ?? runs[0];
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      <div className="mx-auto flex w-full max-w-[920px] flex-col px-6 pb-8">
        <div className="flex items-center gap-3 border-b border-hair pb-2">
          <h2 className="m-0 text-[18px] leading-6 font-bold">Activity</h2>
          <Button variant="tertiary" size="sm" onClick={onBack} className="ml-auto">
            Back to chat
          </Button>
        </div>
        {runs.length === 0 ? (
          <EmptyState
            icon={ListChecks}
            title="No activity yet. Each question appears here with the steps behind its answer."
          />
        ) : (
          <>
            <RunsTable runs={runs} selectedId={selected.runId} onSelect={onSelect} />
            <div className="pt-4">
              <RunDetail run={selected} onRunAgain={onRunAgain} onOpenConversation={onOpenConversation} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
