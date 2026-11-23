import { ApiError, get, post } from "@/lib/api";
import { type LiveBrief, type LiveSitrep, toBrief, toSitrep } from "./adapt";
import type { Brief, SitrepDoc } from "./types";

/** Drafts are visible to command, executive, planning and the drafter; any other role reads no list. */
const sitreps = () =>
  get<LiveSitrep[]>("/api/sitreps").catch((err: unknown) => {
    if (err instanceof ApiError && (err.status === 403 || err.status === 404)) return [];
    throw err;
  });

export const briefApi = {
  brief: async (): Promise<Brief> => {
    const [brief, drafts] = await Promise.all([get<LiveBrief>("/api/brief"), sitreps()]);
    return toBrief(brief, drafts);
  },
  promote: async (runId: string): Promise<SitrepDoc> =>
    toSitrep(await post<LiveSitrep>(`/api/sitreps/${encodeURIComponent(runId)}/promote`, {})),
};
