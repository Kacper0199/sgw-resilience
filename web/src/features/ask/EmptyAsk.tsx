import { CornerDownRight } from "lucide-react";
import { Composer } from "../agent-panel/Composer";
import { PLACEHOLDER, SCOPE, useStarters } from "./starters";

interface Props {
  running: boolean;
  onAsk: (q: string) => void;
  onStop: () => void;
}

/** "Where should we start?": the composer in the middle, four-to-five starters as arrow rows, no Sources panel. */
export function EmptyAsk({ running, onAsk, onStop }: Props) {
  const starters = useStarters();
  return (
    <div
      className="mx-auto flex w-full max-w-[680px] flex-1 flex-col justify-center px-6 pb-16"
      data-testid="starters"
    >
      <h2 className="m-0 text-center text-[32px] leading-10 font-bold tracking-[-0.01em]">
        Where should we start?
      </h2>
      <p className="mx-auto mt-2 mb-6 max-w-[520px] text-center text-[14px] leading-[21px] text-muted">
        Ask about a decision, a procedure or the water network. Ask AI reads SGW documents and platform data,
        and cannot change anything.
      </p>
      <Composer
        running={running}
        placeholder={PLACEHOLDER}
        scope={SCOPE}
        autoFocus
        onSend={onAsk}
        onStop={onStop}
      />
      <ul className="m-0 mt-6 list-none border-t border-hair p-0">
        {starters.map((q) => (
          <li key={q} className="border-b border-hair">
            <button
              type="button"
              disabled={running}
              onClick={() => onAsk(q)}
              className="flex w-full items-start gap-2.5 px-1 py-3 text-left text-[14px] text-ink hover:bg-surface-2 disabled:opacity-45"
            >
              <CornerDownRight aria-hidden className="mt-0.5 size-4 shrink-0 text-muted" />
              {q}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
