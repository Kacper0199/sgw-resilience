import { get, post } from "@/lib/api";
import { agentApi } from "../agent-panel/api";
import type { AfterActionDraft, EtrView, RunAccepted } from "./types";

export const etrApi = {
  view: () => get<EtrView>("/api/etr"),
  draft: async (): Promise<RunAccepted> => {
    const thread = await agentApi.createThread("forecast", "Global ETR");
    return agentApi.createRun(thread.thread_id, "etr", {});
  },
  publish: (runId: string) => post<RunAccepted>(`/api/runs/${encodeURIComponent(runId)}/resume`, {}),
  reviewDrafts: () => get<AfterActionDraft[]>("/api/after-action/drafts"),
  draftReview: () => post<RunAccepted>("/api/after-action/drafts"),
};
