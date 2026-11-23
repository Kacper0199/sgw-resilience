import type { Message } from "./api";
import { toSourceCite } from "./citations";
import { wireExtras } from "./extras";
import { NO_EXTRAS, type RunView, type Turn } from "./types";

export const runIdOf = (messageId: string): string => messageId.split(".")[0] ?? messageId;

/**
 * The transcript of a thread: the server's messages grouped by run, joined with what this browser knows about
 * each run (steps, tools, citation ids). A run the server no longer lists still shows from its local record.
 */
export function buildTurns(messages: readonly Message[], runs: ReadonlyMap<string, RunView>): Turn[] {
  const byRun = new Map<string, Turn>();
  const ensure = (runId: string, at: string): Turn => {
    const hit = byRun.get(runId);
    if (hit) return hit;
    const turn: Turn = {
      runId,
      question: "",
      askedAt: at,
      answerText: null,
      answerAt: null,
      answerPath: null,
      answerReason: null,
      citations: [],
      evidenceIds: [],
      references: [],
      extras: NO_EXTRAS,
      run: runs.get(runId) ?? null,
    };
    byRun.set(runId, turn);
    return turn;
  };

  for (const m of messages) {
    if (m.role === "system") continue;
    const turn = ensure(runIdOf(m.message_id), m.created_at);
    if (m.role === "user") {
      turn.question = m.text;
      turn.askedAt = m.created_at;
    } else {
      turn.answerText = m.text;
      turn.answerAt = m.created_at;
      turn.evidenceIds = m.evidence_ids ?? [];
      turn.answerPath = m.path ?? null;
      turn.answerReason = m.reason ?? null;
      turn.citations = (m.citations ?? []).map(toSourceCite);
      turn.references = m.references ?? [];
      turn.extras = wireExtras(m as unknown as Record<string, unknown>);
    }
  }
  for (const run of runs.values()) {
    const turn = ensure(run.runId, run.startedAt ?? "");
    turn.run = run;
    if (!turn.question && run.question) turn.question = run.question;
    if (run.startedAt && !turn.askedAt) turn.askedAt = run.startedAt;
    if (run.answer) {
      turn.answerText = run.answer.text;
      turn.answerAt = run.answer.at;
      turn.evidenceIds = run.answer.evidenceIds;
      turn.answerPath = run.answer.path ?? turn.answerPath;
      turn.answerReason = run.answer.reason ?? turn.answerReason;
      if (run.answer.citations.length > 0) turn.citations = run.answer.citations;
      if (run.answer.references.length > 0) turn.references = run.answer.references;
      if (run.answer.extras !== NO_EXTRAS) turn.extras = run.answer.extras;
    }
  }
  return [...byRun.values()]
    .filter((t) => t.question || t.answerText || t.run)
    .sort((a, b) => Date.parse(a.askedAt) - Date.parse(b.askedAt));
}
