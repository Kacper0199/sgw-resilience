import type { components } from "@/contracts/api.gen";
import { get, post } from "@/lib/api";
import type { ThreadRun } from "./serverRuns";

export type Thread = components["schemas"]["Thread"];
export type Message = components["schemas"]["Message"];
export type RunAccepted = components["schemas"]["RunAccepted"];
export type RunGraph = components["schemas"]["RunCreate"]["graph"];

export type FeedbackBody = components["schemas"]["RunFeedback"];

const enc = encodeURIComponent;

export const agentApi = {
  createThread: (module: Thread["module"], title: string | null) =>
    post<Thread>("/api/threads", { module, title }),
  createRun: (threadId: string, graph: RunGraph, input: Record<string, unknown>) =>
    post<RunAccepted>(`/api/threads/${enc(threadId)}/runs`, { graph, input }),
  threadRuns: (threadId: string) => get<ThreadRun[]>(`/api/threads/${enc(threadId)}/runs`),
  messages: (threadId: string) => get<Message[]>(`/api/threads/${enc(threadId)}/messages`),
  cancel: (threadId: string, runId: string) =>
    post<void>(`/api/threads/${enc(threadId)}/runs/${enc(runId)}/cancel`),
  feedback: (threadId: string, runId: string, body: FeedbackBody) =>
    post<void>(`/api/threads/${enc(threadId)}/runs/${enc(runId)}/feedback`, body),
};
