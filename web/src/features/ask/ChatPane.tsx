import { useEffect, useRef } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { languageOf } from "../agent-panel/AnswerBody";
import { Composer } from "../agent-panel/Composer";
import type { Turn } from "../agent-panel/types";
import { EmptyAsk } from "./EmptyAsk";
import { inPolish, PLACEHOLDER, useScope, useStarters } from "./starters";
import { TurnView } from "./TurnView";

interface Props {
  turns: Turn[];
  threadId: string | null;
  loading: boolean;
  running: boolean;
  error: string | null;
  activeRunId: string | null;
  activeN: number | null;
  onAsk: (q: string) => void;
  onAskAgain: (q: string) => void;
  onStop: () => void;
  onSelectSource: (runId: string, n: number) => void;
  onShowSources: (runId: string) => void;
  onTrace: (runId: string) => void;
}

/** A question as asked, without a leading "And"/"So" and punctuation: "And which decisions ...?" was asked
 * when "Which decisions ...?" is offered. */
export const sameQuestion = (q: string): string =>
  q
    .toLowerCase()
    .replace(/^\s*(?:and|so|also|then|oraz|a|i)\s+/u, "")
    .replace(/[^\p{L}\p{N} ]/gu, "")
    .replace(/\s+/g, " ")
    .trim();

/** The server's own suggestions when the answer carries some; otherwise two starters not asked yet; never
 * a question already asked in this chat. */
const nextQuestions = (
  turn: Turn,
  starters: readonly string[],
  asked: ReadonlySet<string>,
): readonly string[] =>
  (turn.extras.suggestions.length > 0 ? turn.extras.suggestions : starters).filter(
    (q) => !asked.has(sameQuestion(q)),
  );

export function ChatPane(p: Props) {
  const starters = useStarters();
  const scope = useScope();
  const scroller = useRef<HTMLDivElement>(null);
  const last = p.turns[p.turns.length - 1];
  const signature = `${p.running ? "r" : "i"}:${p.turns.length}:${last?.answerText?.length ?? 0}:${last?.run?.nodes.length ?? 0}`;

  useEffect(() => {
    const el = scroller.current;
    if (el && signature) el.scrollTop = el.scrollHeight;
  }, [signature]);

  if (!p.loading && p.turns.length === 0) {
    return (
      <div data-scroll-region="ask-chat" className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <EmptyAsk running={p.running} onAsk={p.onAsk} onStop={p.onStop} />
        {p.error && (
          <p role="alert" className="mx-auto mb-6 max-w-[680px] px-6 text-[14px] text-crit">
            {p.error}
          </p>
        )}
      </div>
    );
  }

  const asked = new Set(p.turns.map((t) => sameQuestion(t.question)));
  const offered = languageOf(last?.question) === "pl" ? inPolish(starters) : starters;
  const followUps = offered.filter((q) => !asked.has(sameQuestion(q))).slice(0, 2);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        ref={scroller}
        role="log"
        aria-label="Chat"
        // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable log must be reachable by keyboard
        tabIndex={0}
        className="min-h-0 flex-1 overflow-auto px-6 py-4"
      >
        <div className="mx-auto flex w-full max-w-[680px] flex-col gap-8">
          {p.loading ? (
            <div className="space-y-3" role="status" aria-label="Loading chat…">
              <Skeleton className="ml-auto h-9 w-2/3" />
              <Skeleton className="h-20" />
            </div>
          ) : (
            p.turns.map((t, i) => (
              <TurnView
                key={t.runId}
                turn={t}
                threadId={p.threadId ?? t.run?.threadId ?? ""}
                activeN={t.runId === p.activeRunId ? p.activeN : null}
                followUps={i === p.turns.length - 1 && !p.running ? nextQuestions(t, followUps, asked) : []}
                busy={p.running}
                onSelectSource={p.onSelectSource}
                onShowSources={p.onShowSources}
                onTrace={p.onTrace}
                onAskAgain={p.onAskAgain}
                onFollowUp={p.onAsk}
              />
            ))
          )}
          {p.error && (
            <p role="alert" className="m-0 text-[14px] text-crit">
              {p.error}
            </p>
          )}
        </div>
      </div>
      <div className="shrink-0 px-6 pt-2 pb-3">
        <div className="mx-auto w-full max-w-[680px]">
          <Composer
            running={p.running}
            placeholder={PLACEHOLDER}
            scope={scope}
            onSend={p.onAsk}
            onStop={p.onStop}
          />
        </div>
      </div>
    </div>
  );
}
