import { HttpResponse, http } from "msw";
import { meFor } from "@/mocks/fixtures";
import { mockState } from "@/mocks/handlers";
import fixture from "./mock/etr.json";
import type { AfterActionDraft, EtrPublication, EtrView } from "./types";

const PROPOSER = "plan_etr_01";
const PROPOSAL_ID = "PRP-ETR-MOCK0001";
const RUN_ID = "run-etr-mock0001";
const REVIEW_SUMMARY =
  "Two of six deadlines were met. One emergency approval was used and co-signed in time. The global ETR was published once and signed by Command and Operations.";

interface EtrMockState {
  publication: EtrPublication | null;
  drafts: AfterActionDraft[];
}

export const etrMock: EtrMockState = { publication: null, drafts: [] };

export function resetEtrMock(): void {
  etrMock.publication = null;
  etrMock.drafts = [];
}

const base = fixture as EtrView;

function view(userId: string | null): EtrView {
  const pub = etrMock.publication;
  const proposer = userId === PROPOSER;
  const open =
    pub !== null && pub.state !== "expired" && pub.state !== "rejected" && pub.state !== "withdrawn";
  return {
    ...base,
    publication: pub,
    drafting: false,
    can_draft: proposer && !open,
    can_publish: proposer && pub?.state === "approved",
  };
}

export function mockSign(fn: "command" | "operations"): void {
  const pub = etrMock.publication;
  if (!pub || pub.signed_functions.includes(fn)) return;
  const signed = [...pub.signed_functions, fn].sort();
  etrMock.publication = {
    ...pub,
    signed_functions: signed,
    state: signed.length === 2 ? "approved" : "in_review",
  };
}

const signedOut = () =>
  HttpResponse.json({ error: { code: "UNAUTHENTICATED", message: "sign in first" } }, { status: 401 });

/** The agent-panel mock answers every run start first; tests that start the `etr` run put this in front with `server.use`. */
export const draftRunHandler = http.post("/api/threads/:threadId/runs", async ({ request }) => {
  const body = (await request.clone().json()) as { graph?: string };
  if (body.graph !== "etr") return undefined;
  etrMock.publication = {
    proposal_id: PROPOSAL_ID,
    run_id: RUN_ID,
    run_status: "paused",
    state: "proposed",
    proposed_by: PROPOSER,
    estimate_id: base.whole?.estimate_id ?? "",
    p50_utc: base.whole?.p50_utc ?? base.as_of,
    required_functions: ["command", "operations"],
    signed_functions: [],
    created_at: base.as_of,
    published_at: null,
    published_by: null,
    audit_seq: null,
  };
  return HttpResponse.json(
    { run_id: RUN_ID, thread_id: "thr-etr-mock", events_url: "/api/threads/thr-etr-mock/events" },
    { status: 202 },
  );
});

export const handlers = [
  http.get("/api/etr", () => (mockState.userId ? HttpResponse.json(view(mockState.userId)) : signedOut())),
  http.post(`/api/runs/${RUN_ID}/resume`, () => {
    const pub = etrMock.publication;
    if (pub?.state !== "approved")
      return HttpResponse.json({ error: { code: "RUN_NOT_PAUSED", message: "not paused" } }, { status: 409 });
    etrMock.publication = {
      ...pub,
      state: "executed",
      published_at: base.as_of,
      published_by: PROPOSER,
      audit_seq: 812,
    };
    return HttpResponse.json(
      { run_id: RUN_ID, thread_id: "thr-etr-mock", events_url: "/api/threads/thr-etr-mock/events" },
      { status: 202 },
    );
  }),
  http.get("/api/after-action/drafts", () =>
    mockState.userId ? HttpResponse.json(etrMock.drafts) : signedOut(),
  ),
  http.post("/api/after-action/drafts", () => {
    const me = mockState.userId ? meFor(mockState.userId) : null;
    if (!me) return signedOut();
    if (me.function !== "command" && me.function !== "audit")
      return HttpResponse.json(
        { error: { code: "AFTER_ACTION_DRAFT_DENIED", message: "denied" } },
        { status: 403 },
      );
    const runId = `run-aa-mock${etrMock.drafts.length + 1}`;
    etrMock.drafts = [
      {
        run_id: runId,
        thread_id: `thr-aa-mock${etrMock.drafts.length + 1}`,
        drafted_by: me.user_id,
        started_at: "2024-10-06T02:00:00Z",
        as_of_utc: "2024-10-06T02:00:00Z",
        status: "draft",
        path: "llm",
        summary: REVIEW_SUMMARY,
        markdown: `# After-action review (as of 2024-10-06 02:00Z)\n\n${REVIEW_SUMMARY}\n`,
        usable: true,
        classification: "C2",
      },
      ...etrMock.drafts,
    ];
    return HttpResponse.json(
      { run_id: runId, thread_id: "thr-aa", events_url: "/api/threads/thr-aa/events" },
      { status: 202 },
    );
  }),
];
