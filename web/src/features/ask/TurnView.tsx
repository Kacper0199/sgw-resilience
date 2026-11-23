import { TriangleAlert } from "lucide-react";
import { useMemo, useRef } from "react";
import { AnswerActions } from "../agent-panel/AnswerActions";
import { AnswerBody, languageOf } from "../agent-panel/AnswerBody";
import { AnswerEvidence } from "../agent-panel/AnswerEvidence";
import { parseAnswer } from "../agent-panel/parseAnswer";
import type { Turn } from "../agent-panel/types";
import { AnswerLinks } from "./extras/AnswerLinks";
import { PhotoStrip } from "./extras/PhotoStrip";
import { QuestionChips } from "./extras/QuestionChips";
import { StepsLine } from "./StepsLine";
import { sourceCount, sourcesOf } from "./sources";
import { useOpenTrace } from "./trace";

interface Props {
  turn: Turn;
  threadId: string;
  activeN: number | null;
  /** Two questions the AI can answer, offered under the newest answer only. */
  followUps: readonly string[];
  busy: boolean;
  onSelectSource: (runId: string, n: number) => void;
  onShowSources: (runId: string) => void;
  onTrace: (runId: string) => void;
  onAskAgain: (question: string) => void;
  onFollowUp: (question: string) => void;
}

export function TurnView({
  turn,
  threadId,
  activeN,
  followUps,
  busy,
  onSelectSource,
  onShowSources,
  onTrace,
  onAskAgain,
  onFollowUp,
}: Props) {
  const { run } = turn;
  const openTrace = useOpenTrace();
  const parsed = useMemo(() => {
    if (!turn.answerText) return null;
    const answer = parseAnswer(turn.answerText, turn.answerPath ?? run?.answer?.path);
    return turn.citations.length > 0 ? { ...answer, citations: turn.citations } : answer;
  }, [turn.answerText, turn.answerPath, turn.citations, run?.answer?.path]);
  const working = run?.status === "running" && !parsed;
  const watched = useRef(false);
  if (working) watched.current = true;
  const failed = run && (run.status === "error" || run.status === "cancelled") && !parsed;
  const sources = sourceCount(sourcesOf(parsed, run, turn.references));
  const unavailable = parsed?.kind === "not_in_documents" && turn.answerReason === "llm_unavailable";
  const polish = languageOf(turn.question) === "pl";

  return (
    <article className="flex flex-col gap-3" data-testid="turn" aria-label={`Question: ${turn.question}`}>
      <p
        data-testid="user-message"
        className="m-0 max-w-[85%] self-end rounded-[18px] bg-surface-3 px-4 py-2.5 text-[15px] leading-6 break-words whitespace-pre-line"
      >
        {turn.question}
      </p>

      <div className="flex min-w-0 flex-col gap-3">
        {working && (
          <section aria-live="polite" aria-label="Working on an answer…">
            <StepsLine run={run} onDetails={() => onTrace(turn.runId)} lang={polish ? "pl" : "en"} />
          </section>
        )}

        {failed && (
          <p role="alert" className="m-0 flex items-start gap-2 text-[14px] text-crit">
            <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
            {run.status === "cancelled"
              ? "Stopped before the answer was written."
              : (run.error ?? "Couldn't finish this answer.")}
          </p>
        )}

        {parsed && (
          <>
            {run && run.nodes.length > 0 && (
              <StepsLine run={run} onDetails={() => onTrace(turn.runId)} lang={polish ? "pl" : "en"} />
            )}
            <div
              className={`flex min-w-0 flex-col gap-3${watched.current ? " sgw-reveal" : ""}`}
              data-testid="answer"
            >
              <AnswerBody
                parsed={parsed}
                reason={turn.answerReason}
                tainted={run?.answer?.tainted ?? false}
                activeN={activeN}
                onSelect={(n) => onSelectSource(turn.runId, n)}
                references={turn.references}
                question={turn.question}
              />
              {parsed.kind === "not_in_documents" && <AnswerEvidence run={run} />}
              <QuestionChips
                questions={turn.extras.didYouMean}
                busy={busy}
                onAsk={onFollowUp}
                label={polish ? "Czy chodziło o" : "Did you mean"}
              />
              <PhotoStrip photos={turn.extras.photos} />
              <AnswerLinks links={turn.extras.links} />
              <AnswerActions
                threadId={threadId}
                runId={turn.runId}
                copyText={turn.answerText ?? ""}
                sourceCount={sources}
                polish={polish}
                hasTrace={Boolean(run)}
                canAskAgain={!busy}
                unavailable={unavailable}
                onTrace={() => onTrace(turn.runId)}
                onHowMade={openTrace ? () => openTrace(turn.runId) : undefined}
                onAskAgain={() => onAskAgain(turn.question)}
                onShowSources={() => onShowSources(turn.runId)}
              />
              {followUps.length > 0 && !unavailable && turn.extras.didYouMean.length === 0 && (
                <QuestionChips
                  questions={followUps}
                  busy={busy}
                  onAsk={onFollowUp}
                  label={polish ? "Pytania na dalej" : undefined}
                />
              )}
            </div>
          </>
        )}
      </div>
    </article>
  );
}
