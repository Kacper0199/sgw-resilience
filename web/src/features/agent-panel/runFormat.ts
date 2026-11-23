import { formatZ } from "@/lib/time";
import { inferPath } from "./parseAnswer";
import type { AnswerPath, RunView } from "./types";

export const PATH_LABEL: Record<AnswerPath, string> = {
  llm: "Answer with sources",
  m2: "Answer from platform data",
  not_in_documents: "No match in documents",
  guide: "Platform guide",
};

export function runPath(run: RunView): AnswerPath | null {
  if (!run.answer) return null;
  return run.answer.path ?? inferPath(run.answer.text);
}

export function elapsedMs(run: RunView): number | null {
  if (!run.startedAt || !run.endedAt) return null;
  return Math.max(0, Date.parse(run.endedAt) - Date.parse(run.startedAt));
}

export function formatElapsed(ms: number | null): string {
  if (ms === null) return "running";
  return ms < 950 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export const offsetLabel = (run: RunView, at: string): string =>
  run.startedAt ? `+${((Date.parse(at) - Date.parse(run.startedAt)) / 1000).toFixed(1)} s` : formatZ(at);

export const STATUS_WORD: Record<RunView["status"], string> = {
  running: "Running",
  done: "Done",
  error: "Failed",
  cancelled: "Stopped",
  paused: "Paused",
};
