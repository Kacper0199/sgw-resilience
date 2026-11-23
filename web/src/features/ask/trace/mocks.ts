import { HttpResponse, http } from "msw";
import { mockState } from "@/mocks/handlers";
import { liveFailedRun, multiAgentRun } from "./fixtures";

const SHOWN = /^(run-mock-|RUN-0047$)/;
const LIVE_FAILED = "RUN-0044";

/** The multi-agent trace for the mock Ask runs, one replayed request and one live request with a failed check; every other run id falls through to the Health mock. */
export const handlers = [
  http.get("/api/runs/:id", ({ params }) => {
    const id = String(params.id);
    if (mockState.userId && id === LIVE_FAILED) return HttpResponse.json(liveFailedRun(id));
    return mockState.userId && SHOWN.test(id) ? HttpResponse.json(multiAgentRun(id)) : undefined;
  }),
];
