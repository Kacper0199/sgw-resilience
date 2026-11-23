import { toolVerb } from "./labels";
import { plainToolArg } from "./ToolChip";
import type { RunView } from "./types";

/** An abstain says where it looked. A sourced answer needs no such line: its sources are in the Sources panel. */
export function AnswerEvidence({ run }: { run: RunView | null }) {
  const looked = run?.tools ?? [];
  if (looked.length === 0) return null;
  return (
    <p
      className="m-0 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[13px]"
      data-testid="answer-evidence"
    >
      <span className="text-muted">Looked at</span>
      {looked.map((t) => (
        <span key={t.call} className="rounded-sm bg-surface-3 px-1.5 py-0.5 text-[12px]">
          {toolVerb(t.tool)}
          {plainToolArg(t.args) && <span className="text-muted">: {plainToolArg(t.args)}</span>}
        </span>
      ))}
    </p>
  );
}
