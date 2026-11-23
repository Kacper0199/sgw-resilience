import { delay, HttpResponse, http } from "msw";
import type { LiveBrief, LiveSitrep } from "./adapt";
import { initialLiveBrief, initialSitreps, makeSitrep } from "./mocks/data";

let brief: LiveBrief = initialLiveBrief();
let sitreps: LiveSitrep[] = initialSitreps();

export function resetBriefMock(): void {
  brief = initialLiveBrief();
  sitreps = initialSitreps();
}
const error = (status: number, code: string, message: string) =>
  HttpResponse.json({ error: { code, message } }, { status });

/** Called by the shared thread mock when a sitrep run finishes, so the next GET /api/sitreps carries the draft. */
export function recordSitrepDraft(runId: string): void {
  sitreps = [makeSitrep(runId, false), ...sitreps.filter((s) => s.run_id !== runId)];
}

export const handlers = [
  http.get("/api/brief", async () => {
    await delay(40);
    return HttpResponse.json(brief);
  }),
  http.get("/api/sitreps", () => HttpResponse.json(sitreps)),
  http.post("/api/sitreps/:runId/promote", ({ params }) => {
    const draft = sitreps.find((s) => s.run_id === params.runId && s.status === "draft");
    if (!draft) return error(404, "NOT_FOUND", "no such draft");
    const promoted = {
      ...draft,
      status: "promoted" as const,
      promoted_by: "ic_01",
      promoted_at: brief.as_of,
    };
    sitreps = sitreps.map((s) => (s.run_id === draft.run_id ? promoted : s));
    return HttpResponse.json(promoted);
  }),
];
