import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import type { WireFrame } from "@/contracts/wire.gen";
import { ApiError } from "@/lib/api";
import { agentApi, type RunGraph } from "./api";
import { followRun } from "./followRun";
import { emptyRun, isTerminal, reduceRunFrame } from "./reduceRun";
import type { RunView } from "./types";

type Action =
  | { type: "begin"; view: RunView }
  | { type: "frame"; runId: string; frame: WireFrame; id: string | undefined }
  | { type: "lost"; runId: string }
  | { type: "seed"; views: RunView[] };

function reducer(state: Record<string, RunView>, action: Action): Record<string, RunView> {
  switch (action.type) {
    case "begin":
      return { ...state, [action.view.runId]: action.view };
    case "frame": {
      const run = state[action.runId];
      return run ? { ...state, [action.runId]: reduceRunFrame(run, action.frame, action.id) } : state;
    }
    case "lost": {
      const run = state[action.runId];
      if (!run || isTerminal(run)) return state;
      return {
        ...state,
        [action.runId]: {
          ...run,
          status: "error",
          error: "Connection lost. Reload the page to see the answer if it finished.",
        },
      };
    }
    case "seed": {
      const next = { ...state };
      for (const v of action.views) if (!next[v.runId]) next[v.runId] = v;
      return next;
    }
  }
}

export function startErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "RUN_ACTIVE") return "An answer is still being written. Wait, or stop it.";
    if (err.code === "GRAPH_NOT_AVAILABLE") return "Ask AI isn't available yet.";
    if (err.status === 403) return "Your role can't use this.";
    return err.message;
  }
  return "Can't reach SGW. Check your connection.";
}

export interface StartArgs {
  threadId: string;
  graph: RunGraph;
  input: Record<string, unknown>;
  question: string | null;
}

/** Starts agent runs and keeps a live view of each one from its SSE stream; closes streams on unmount. */
export function useAgentRuns(onFinished?: (run: RunView) => void) {
  const [runs, dispatch] = useReducer(reducer, {} as Record<string, RunView>);
  const [startError, setStartError] = useState<string | null>(null);
  const controllers = useRef(new Map<string, AbortController>());
  const finished = useRef(new Set<string>());
  const notify = useRef(onFinished);
  notify.current = onFinished;

  useEffect(
    () => () => {
      for (const c of controllers.current.values()) c.abort();
    },
    [],
  );

  useEffect(() => {
    for (const run of Object.values(runs)) {
      if (isTerminal(run) && !finished.current.has(run.runId)) {
        finished.current.add(run.runId);
        notify.current?.(run);
      }
    }
  }, [runs]);

  const start = useCallback(async (args: StartArgs): Promise<RunView | null> => {
    setStartError(null);
    let accepted: Awaited<ReturnType<typeof agentApi.createRun>>;
    try {
      accepted = await agentApi.createRun(args.threadId, args.graph, args.input);
    } catch (err) {
      setStartError(startErrorMessage(err));
      return null;
    }
    const view = emptyRun(accepted.run_id, args.threadId, args.graph, args.question);
    dispatch({ type: "begin", view });
    const ctl = new AbortController();
    controllers.current.set(view.runId, ctl);
    void followRun({
      url: accepted.events_url,
      signal: ctl.signal,
      onFrame: (frame, id) => dispatch({ type: "frame", runId: view.runId, frame, id }),
    }).then((result) => {
      controllers.current.delete(view.runId);
      if (result === "failed") dispatch({ type: "lost", runId: view.runId });
    });
    return view;
  }, []);

  const stop = useCallback((run: RunView) => {
    void agentApi.cancel(run.threadId, run.runId).catch(() => undefined);
  }, []);

  const seed = useCallback((views: RunView[]) => dispatch({ type: "seed", views }), []);

  return { runs, start, stop, seed, startError, clearError: () => setStartError(null) };
}
