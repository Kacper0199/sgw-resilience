import type { RunView } from "./types";

export interface LocalThread {
  threadId: string;
  title: string;
  createdAt: string;
}

export interface RunRecord {
  runId: string;
  threadId: string;
  graph: string;
  question: string;
  status: RunView["status"];
  startedAt: string | null;
  endedAt: string | null;
  run: RunView;
}

const MAX_THREADS = 30;
const MAX_RUNS = 40;
const threadsKey = (user: string) => `sgw.ask.threads.${user}`;
const runsKey = (user: string) => `sgw.ask.runs.${user}`;

function read<T>(key: string): T[] {
  try {
    const raw = localStorage.getItem(key);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage full or blocked: history is a convenience, never required.
  }
}

export const loadThreads = (user: string): LocalThread[] =>
  read<LocalThread>(threadsKey(user)).filter((t) => typeof t.threadId === "string");

export function saveThread(user: string, thread: LocalThread): LocalThread[] {
  const all = [thread, ...loadThreads(user).filter((t) => t.threadId !== thread.threadId)].slice(
    0,
    MAX_THREADS,
  );
  write(threadsKey(user), all);
  return all;
}

export const loadRuns = (user: string): RunRecord[] =>
  read<RunRecord>(runsKey(user)).filter((r) => typeof r.runId === "string" && r.run);

export function saveRun(user: string, run: RunView): RunRecord[] {
  const record: RunRecord = {
    runId: run.runId,
    threadId: run.threadId,
    graph: run.graph,
    question: run.question ?? "",
    status: run.status,
    startedAt: run.startedAt,
    endedAt: run.endedAt,
    run,
  };
  const all = [record, ...loadRuns(user).filter((r) => r.runId !== run.runId)].slice(0, MAX_RUNS);
  write(runsKey(user), all);
  return all;
}
