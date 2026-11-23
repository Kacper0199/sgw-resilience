import { useQuery, useQueryClient } from "@tanstack/react-query";
import { parseAsString, useQueryState } from "nuqs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useMe } from "@/auth/useSession";
import { useWorld } from "@/lib/world";
import { agentApi } from "../agent-panel/api";
import { buildTurns } from "../agent-panel/buildTurns";
import { type LocalThread, loadRuns, loadThreads, saveRun, saveThread } from "../agent-panel/localHistory";
import { runViewOf } from "../agent-panel/serverRuns";
import type { RunView, Turn } from "../agent-panel/types";
import { startErrorMessage, useAgentRuns } from "../agent-panel/useAgentRuns";

const TITLE_MAX = 60;
const shorten = (q: string) => (q.length > TITLE_MAX ? `${q.slice(0, TITLE_MAX - 1)}…` : q);

/** The database (`useWorld`) each thread was opened in: a loaded scenario or moment replaces it, and its threads with it. */
const openedIn = new Map<string, number>();

export function useAsk() {
  const qc = useQueryClient();
  const userId = useMe().data?.user_id ?? "anonymous";
  const [urlThread, setThreadId] = useQueryState("t", parseAsString);
  const world = useWorld();
  if (urlThread && !openedIn.has(urlThread)) openedIn.set(urlThread, world);
  const gone = urlThread !== null && openedIn.get(urlThread) !== world;
  const threadId = gone ? null : urlThread;
  useEffect(() => {
    if (gone) void setThreadId(null);
  }, [gone, setThreadId]);
  const [threads, setThreads] = useState<LocalThread[]>(() => loadThreads(userId));
  const [records, setRecords] = useState<RunView[]>(() => loadRuns(userId).map((r) => r.run));
  const [error, setError] = useState<string | null>(null);

  const live = useAgentRuns((run) => {
    setRecords(saveRun(userId, run).map((r) => r.run));
    void qc.invalidateQueries({ queryKey: ["ask", "messages", run.threadId] });
    void qc.invalidateQueries({ queryKey: ["ask", "runs", run.threadId] });
  });

  const messages = useQuery({
    queryKey: ["ask", "messages", threadId],
    queryFn: () => agentApi.messages(threadId as string),
    enabled: Boolean(threadId),
    retry: false,
  });

  const serverRuns = useQuery({
    queryKey: ["ask", "runs", threadId],
    queryFn: () => agentApi.threadRuns(threadId as string),
    enabled: Boolean(threadId),
    retry: false,
  });

  const runMap = useMemo(() => {
    const map = new Map<string, RunView>();
    const server = new Map((serverRuns.data ?? []).map((r) => [r.run_id, r]));
    for (const r of serverRuns.data ?? []) map.set(r.run_id, runViewOf(threadId as string, r));
    const timed = (r: RunView): RunView => {
      const s = server.get(r.runId);
      return s?.ended_at ? { ...r, startedAt: s.started_at, endedAt: s.ended_at } : r;
    };
    for (const r of records) map.set(r.runId, timed(r));
    for (const r of Object.values(live.runs)) map.set(r.runId, timed(r));
    return map;
  }, [serverRuns.data, threadId, records, live.runs]);

  const allRuns = useMemo(
    () =>
      [...runMap.values()]
        .filter((r) => r.graph === "copilot")
        .sort((a, b) => Date.parse(b.startedAt ?? "") - Date.parse(a.startedAt ?? "")),
    [runMap],
  );

  const turns: Turn[] = useMemo(() => {
    if (!threadId) return [];
    const mine = new Map([...runMap].filter(([, r]) => r.threadId === threadId && r.graph === "copilot"));
    return buildTurns(messages.data ?? [], mine);
  }, [threadId, messages.data, runMap]);

  const active = allRuns.find((r) => r.threadId === threadId && r.status === "running") ?? null;

  const ensureThread = useCallback(
    async (question: string): Promise<string | null> => {
      if (threadId) return threadId;
      try {
        const t = await agentApi.createThread("ask", shorten(question));
        setThreads(
          saveThread(userId, { threadId: t.thread_id, title: shorten(question), createdAt: t.created_at }),
        );
        await setThreadId(t.thread_id);
        return t.thread_id;
      } catch (err) {
        setError(startErrorMessage(err));
        return null;
      }
    },
    [threadId, userId, setThreadId],
  );

  const ask = useCallback(
    async (question: string, inThread?: string) => {
      setError(null);
      const id = inThread ?? (await ensureThread(question));
      if (!id) return;
      await live.start({ threadId: id, graph: "copilot", input: { question }, question });
    },
    [ensureThread, live],
  );

  return {
    userId,
    threadId,
    threads,
    turns,
    runs: allRuns,
    messagesLoading: messages.isPending && Boolean(threadId),
    active,
    error: error ?? live.startError,
    clearError: () => {
      setError(null);
      live.clearError();
    },
    ask,
    stop: live.stop,
    openThread: (id: string | null) => setThreadId(id),
  };
}
