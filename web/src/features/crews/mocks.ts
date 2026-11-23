import { HttpResponse, http } from "msw";
import type { components } from "@/contracts/api.gen";
import damage from "./mocks/damage.json";
import ladi from "./mocks/ladi-report.json";
import plan from "./mocks/plan.json";
import { mockThumbUrl } from "./mocks/thumbs";
import type { CrewItem } from "./types";

type Assignment = components["schemas"]["CrewAssignment"];
type Target = components["schemas"]["CrewTarget"];
type Action = NonNullable<CrewItem["actions"]>[number];

/** Crew roster of the detail area (`data/synthetic/helene.yaml`). Statuses and shift ends are assumed for the mock. */
export const crews: CrewItem[] = [
  {
    crew_id: "CRW-OSPREY-04",
    status: "staged",
    location_id: "STG-AIK-SANDHILL-YARD",
    headcount: 24,
    shift_end: "2024-09-27T10:00:00Z",
  },
  {
    crew_id: "CRW-KESTREL-02",
    status: "staged",
    location_id: "STG-AIK-SANDHILL-YARD",
    headcount: 24,
    shift_end: "2024-09-27T10:00:00Z",
  },
  {
    crew_id: "CRW-OSPREY-07",
    status: "staged",
    location_id: "STG-RCH-MILLPOND-YARD",
    headcount: 24,
    shift_end: "2024-09-27T10:00:00Z",
  },
  {
    crew_id: "CRW-MA-TALON-11",
    status: "enroute",
    location_id: "STG-RCH-MILLPOND-YARD",
    headcount: 40,
    shift_end: null,
  },
  { crew_id: "CRW-HARRIER-0103", status: "available", location_id: null, headcount: 24, shift_end: null },
  { crew_id: "CRW-MERLIN-0102", status: "available", location_id: null, headcount: 24, shift_end: null },
];

export const targets: Target[] = [
  {
    kind: "decision",
    target_id: "DC-D3-PS17-POWER",
    label: "Hook up the portable generator at PS-17",
    proposal_id: "PRP-PS17-FDR2207-PRIO",
  },
  {
    kind: "decision",
    target_id: "DC-D2-CREWS-AIK",
    label: "Pre-position crews at Sandhill and Millpond yards",
    proposal_id: "PRP-AIK-STAGE",
  },
  { kind: "yard", target_id: "STG-AIK-SANDHILL-YARD", label: "Sandhill yard", proposal_id: null },
  { kind: "yard", target_id: "STG-RCH-MILLPOND-YARD", label: "Millpond yard", proposal_id: null },
];

/** Mock dispatch: the same rules as `sgw.dispatch` (who acts, who signs, which moves fit the state). */
const ACTORS = new Set(["ops_dm_01", "ops_dm_02", "log_01"]);
const FUNCTION_OF: Record<string, "logistics" | "operations"> = {
  log_01: "logistics",
  ops_dm_01: "operations",
  ops_dm_02: "operations",
};
const ARRIVAL = { decision: "onsite", yard: "staged" } as const;
const dispatch = new Map<
  string,
  { status: CrewItem["status"]; assignment: Assignment | null; before?: CrewItem }
>();

const who = () => (typeof sessionStorage === "undefined" ? null : sessionStorage.getItem("sgw.mock.user"));

export function resetDispatch(): void {
  dispatch.clear();
}

function current(c: CrewItem): CrewItem {
  const d = dispatch.get(c.crew_id);
  return d
    ? { ...c, status: d.status, assignment: d.assignment, block_reason: d.before?.block_reason ?? null }
    : c;
}

function actionsFor(c: CrewItem, user: string | null): Action[] {
  const a = c.assignment ?? null;
  const out: Action[] = [];
  if (
    a?.state === "proposed" &&
    user &&
    user !== a.proposed_by &&
    FUNCTION_OF[user] === a.required_function
  ) {
    out.push("sign", "reject");
  }
  if (!user || !ACTORS.has(user)) return out;
  const blocked = c.status === "blocked";
  if (!a && !blocked && c.status !== "off_shift") out.push("assign");
  if (a?.state === "proposed") out.push("withdraw");
  if (a?.state === "assigned" && !blocked) {
    const arrival = ARRIVAL[a.target_kind];
    if (c.status !== "enroute" && c.status !== arrival) out.push("enroute");
    if (c.status !== arrival) out.push(arrival);
  }
  out.push(blocked ? "unblock" : "block");
  if (a?.state === "assigned") out.push("release");
  return out;
}

const roster = () => {
  const user = who();
  return crews.map(current).map((c) => ({ ...c, actions: actionsFor(c, user) }));
};

const problem = (status: number, code: string) =>
  HttpResponse.json(
    { error: { code, message: code.toLowerCase().replaceAll("_", " "), details: {} } },
    { status },
  );

function crewOf(id: string) {
  return roster().find((c) => c.crew_id === id);
}

export const handlers = [
  http.get("/api/crews", () => HttpResponse.json(roster())),
  http.get("/api/crews/targets", () => HttpResponse.json(targets)),
  http.post("/api/crews/:id/assignments", async ({ params, request }) => {
    const c = crewOf(String(params.id));
    if (!c) return problem(404, "CREW_NOT_FOUND");
    if (!c.actions.includes("assign")) return problem(c.actions.length ? 409 : 403, "DISPATCH_DENIED");
    const body = (await request.json()) as { target_kind: string; target_id: string };
    const t = targets.find((x) => x.kind === body.target_kind && x.target_id === body.target_id);
    if (!t) return problem(422, "UNKNOWN_DISPATCH_TARGET");
    const user = who() ?? "";
    const assignment: Assignment = {
      assignment_id: `ASG-${String(dispatch.size + 1).padStart(16, "0")}`,
      target_kind: t.kind,
      target_id: t.target_id,
      target_label: t.label,
      decision_proposal_id: t.proposal_id ?? null,
      state: "proposed",
      required_function: FUNCTION_OF[user] === "logistics" ? "operations" : "logistics",
      proposed_by: user,
      proposed_at: "2024-09-26T15:05:00Z",
      decided_by: null,
      decided_at: null,
    };
    dispatch.set(c.crew_id, { status: c.status, assignment });
    return HttpResponse.json(
      { crew_id: c.crew_id, assignment_id: assignment.assignment_id },
      { status: 201 },
    );
  }),
  http.post("/api/crews/:id/assignment/sign", async ({ params, request }) => {
    const c = crewOf(String(params.id));
    const d = dispatch.get(String(params.id));
    if (!c || !d?.assignment) return problem(409, "NOT_PENDING");
    if (!c.actions.includes("sign")) return problem(403, "SIGN_DENIED");
    const { decision } = (await request.json()) as { decision: "approve" | "reject" };
    d.assignment =
      decision === "approve"
        ? { ...d.assignment, state: "assigned", decided_by: who(), decided_at: "2024-09-26T15:05:00Z" }
        : null;
    return HttpResponse.json({ crew_id: c.crew_id, assignment_id: null });
  }),
  http.post("/api/crews/:id/assignment/withdraw", ({ params }) => {
    const c = crewOf(String(params.id));
    const d = dispatch.get(String(params.id));
    if (!c || !d || !c.actions.includes("withdraw")) return problem(409, "NOT_PENDING");
    d.assignment = null;
    return HttpResponse.json({ crew_id: c.crew_id, assignment_id: null });
  }),
  http.post("/api/crews/:id/status", async ({ params, request }) => {
    const c = crewOf(String(params.id));
    if (!c) return problem(404, "CREW_NOT_FOUND");
    const { move, block_reason } = (await request.json()) as {
      move: string;
      block_reason: CrewItem["block_reason"];
    };
    const action = (move === "blocked" ? "block" : move) as Action;
    if (!c.actions.includes(action)) return problem(c.actions.length ? 409 : 403, "CREW_MOVE_NOT_ALLOWED");
    const d = dispatch.get(c.crew_id) ?? { status: c.status, assignment: null };
    if (move === "blocked") {
      if (!block_reason) return problem(422, "BLOCK_REASON_REQUIRED");
      d.before = { ...c, block_reason };
      d.status = "blocked";
    } else if (move === "unblock") {
      d.status = d.before?.status ?? "available";
      d.before = undefined;
    } else if (move === "release") {
      d.assignment = null;
      d.status = "available";
    } else {
      d.status = move as CrewItem["status"];
    }
    dispatch.set(c.crew_id, d);
    return HttpResponse.json({ crew_id: c.crew_id, assignment_id: null });
  }),
  http.get("/api/crews/plan", () => HttpResponse.json(plan)),
  http.get("/api/damage/queue", () => HttpResponse.json(damage)),
  http.get("/api/damage/thumbs/:id", async ({ params }) => {
    const url = mockThumbUrl(String(params.id));
    if (!url) return new HttpResponse(null, { status: 404 });
    const res = await fetch(url);
    return new HttpResponse(await res.arrayBuffer(), { headers: { "content-type": "image/jpeg" } });
  }),
  http.get("/api/damage/photos/:id", ({ params }) => {
    const id = String(params.id);
    const row = damage.rows.find((r) => r.image_id === id);
    if (!row) return problem(404, "PHOTO_NOT_FOUND");
    const labels = row.signals.map((label, i) => ({ label, score: Math.max(0.05, 0.92 - i * 0.17) }));
    return HttpResponse.json({
      image_id: id,
      rank: row.rank,
      triage_score: row.triage_score,
      signals: row.signals,
      labels: [...labels, { label: "bridges_any", score: 0.01 }],
      suggested_actions: row.suggested_actions,
      human_only: row.human_only,
      seeded_case_id: row.seeded_case_id,
      status: row.status,
      image_url: `/api/damage/thumbs/${id}`,
      full_size: false,
      dataset: "MITLL/LADI-v2-dataset",
      licence: "CC-BY-4.0",
      model_id: "MITLL/LADI-v2-classifier-small-reference",
    });
  }),
  http.get("/api/models/ladi_reference/evaluation", () => HttpResponse.json(ladi)),
];
