import { HttpResponse, http } from "msw";
import { FUNCTION_LABEL, PERSONAS } from "@/auth/personas";
import { mockState } from "@/mocks/handlers";
import heat from "./hazard-heat.mock.json";
import wildfire from "./hazard-wildfire.mock.json";
import type { HeatView, WildfireView } from "./hazardTypes";
import type { ReadinessItem, ReadinessRecord } from "./types";

const REVIEW = "2024-05-06T12:00:00Z";

/** The six WP-22 blue-sky cases as read at their pre-season review (Mon 6 May 2024 08:00 ET), with their effective decide-by dates. */
export const readinessItems: ReadinessItem[] = [
  {
    item_id: "DC-RDY-GEN-PS52-LOADTEST",
    title: "Annual load test on the Deerwater pump-station generator",
    domain: "water",
    status: "gap",
    owner_function: "operations",
    due_utc: "2024-04-19T04:00:00Z",
    evaluated_at_utc: REVIEW,
  },
  {
    item_id: "DC-RDY-STAGE-SANDHILL-LEASE",
    title: "Sandhill staging yard lease and fuel on site",
    domain: "electric",
    status: "gap",
    owner_function: "logistics",
    due_utc: "2024-05-11T04:00:00Z",
    evaluated_at_utc: REVIEW,
  },
  {
    item_id: "DC-RDY-MAID-TALON-MOU",
    title: "Mutual-aid agreement with the Talon task force",
    domain: "electric",
    status: "unknown",
    owner_function: "logistics",
    due_utc: "2024-05-18T04:00:00Z",
    evaluated_at_utc: REVIEW,
  },
  {
    item_id: "DC-RDY-VEG-FDR2207-2231",
    title: "Vegetation cleared on the hospital feeder trunks",
    domain: "electric",
    status: "ready",
    owner_function: "operations",
    due_utc: "2024-05-18T04:00:00Z",
    evaluated_at_utc: REVIEW,
  },
  {
    item_id: "DC-RDY-FUEL-PS38-PS52-TOPUP",
    title: "Pump-station fuel tanks topped up, priority delivery agreed",
    domain: "water",
    status: "gap",
    owner_function: "logistics",
    due_utc: "2024-05-22T04:00:00Z",
    evaluated_at_utc: REVIEW,
  },
  {
    item_id: "DC-RDY-TANKER-TALLOWBRANCH",
    title: "Standby potable-water tanker for the Tallowbranch hospital",
    domain: "water",
    status: "ready",
    owner_function: "water_operations",
    due_utc: "2024-05-25T04:00:00Z",
    evaluated_at_utc: REVIEW,
  },
];

export const ownerLabel = (item: ReadinessItem) => FUNCTION_LABEL[item.owner_function];

export const heatLibrary = heat as HeatView;
export const wildfireLibrary = wildfire as WildfireView;

const STATUS_OF: Record<ReadinessRecord["status"], ReadinessItem["status"]> = {
  ready: "ready",
  not_ready: "gap",
  waived: "waived",
};

const recorded = new Map<string, NonNullable<ReadinessItem["result"]>>();

export const resetReadinessResults = () => recorded.clear();

const current = (): ReadinessItem[] =>
  readinessItems.map((i) => {
    const result = recorded.get(i.item_id);
    return result ? { ...i, status: STATUS_OF[result.status], result } : i;
  });

/** Mirrors `readiness_record` of `GET /api/me/permissions`: the checks the persona's function owns. */
export const recordableBy = (userId: string): string[] => {
  const fn = PERSONAS.find((p) => p.user_id === userId)?.function;
  return readinessItems.filter((i) => i.owner_function === fn).map((i) => i.item_id);
};

const unauthenticated = () =>
  HttpResponse.json({ error: { code: "UNAUTHENTICATED", message: "sign in first" } }, { status: 401 });

export const handlers = [
  http.get("/api/hazards/library/heat", () =>
    mockState.userId ? HttpResponse.json(heatLibrary) : unauthenticated(),
  ),
  http.get("/api/hazards/library/wildfire", () =>
    mockState.userId ? HttpResponse.json(wildfireLibrary) : unauthenticated(),
  ),
  http.get("/api/readiness", () => (mockState.userId ? HttpResponse.json(current()) : unauthenticated())),
  http.post<{ id: string }, ReadinessRecord>("/api/readiness/:id", async ({ params, request }) => {
    const user = mockState.userId;
    if (!user) return unauthenticated();
    if (!recordableBy(user).includes(params.id))
      return HttpResponse.json(
        { error: { code: "READINESS_NOT_OWNER", message: "only the owner records this check" } },
        { status: 403 },
      );
    const body = await request.json();
    recorded.set(params.id, {
      status: body.status,
      note: body.note,
      evidence_url: body.evidence_url ?? null,
      recorded_by: user,
      recorded_at_utc: new Date().toISOString(),
      reviewed_at_utc: REVIEW,
    });
    return HttpResponse.json(current().find((i) => i.item_id === params.id));
  }),
];
