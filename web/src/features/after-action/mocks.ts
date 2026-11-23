import { delay, HttpResponse, http } from "msw";
import scReport from "./mocks/sc-report.json";
import scorecard from "./mocks/scorecard.json";
import type { AfterAction, AuditVerifyResult, Scorecard, ScReport, TamperDemo, TimelineEntry } from "./types";

const BROKEN_KEY = "sgw.mock.chain_broken_at";
const AS_OF = "2024-09-28T18:00:00Z";
const HEAD_SEQ = 1204;

const brokenAt = (): number | null => {
  const v = typeof sessionStorage === "undefined" ? null : sessionStorage.getItem(BROKEN_KEY);
  return v ? Number(v) : null;
};

const t = (
  seq: number,
  occurred_at: string,
  kind: string,
  actor_id: string,
  subject: string,
): TimelineEntry => ({
  seq,
  occurred_at,
  kind,
  actor_id,
  subject,
});

export const timeline: TimelineEntry[] = [
  t(311, "2024-09-26T01:02:10Z", "proposal_created", "plan_01", "proposal:PRP-CREW-AIK-0926A"),
  t(318, "2024-09-26T01:14:40Z", "approval_recorded", "ic_01", "proposal:PRP-CREW-AIK-0926A"),
  t(319, "2024-09-26T01:21:05Z", "approval_recorded", "log_01", "proposal:PRP-CREW-AIK-0926A"),
  t(320, "2024-09-26T01:21:05Z", "execution_token_issued", "system", "proposal:PRP-CREW-AIK-0926A"),
  t(402, "2024-09-26T13:20:00Z", "proposal_created", "plan_01", "proposal:PRP-MUTUAL-AID-0926B"),
  t(409, "2024-09-26T14:36:12Z", "break_glass_used", "ic_01", "proposal:PRP-MUTUAL-AID-0926B"),
  t(410, "2024-09-26T14:36:12Z", "execution_token_issued", "system", "proposal:PRP-MUTUAL-AID-0926B"),
  t(655, "2024-09-27T01:12:30Z", "approval_recorded", "wtr_lead_01", "proposal:PRP-PS17-FUEL"),
  t(656, "2024-09-27T01:12:55Z", "approval_recorded", "ops_dm_01", "proposal:PRP-PS17-FUEL"),
  t(657, "2024-09-27T01:12:55Z", "execution_token_issued", "system", "proposal:PRP-PS17-FUEL"),
  t(701, "2024-09-27T02:50:20Z", "approval_recorded", "wtr_lead_01", "proposal:PRP-PS17-FDR2207-PRIO"),
  t(702, "2024-09-27T02:50:41Z", "approval_recorded", "ops_dm_01", "proposal:PRP-PS17-FDR2207-PRIO"),
  t(703, "2024-09-27T02:50:41Z", "execution_token_issued", "system", "proposal:PRP-PS17-FDR2207-PRIO"),
  t(760, "2024-09-27T06:20:10Z", "approval_recorded", "wtr_lead_01", "proposal:PRP-PS17-PRESSURE"),
  t(761, "2024-09-27T06:20:30Z", "approval_recorded", "ops_dm_01", "proposal:PRP-PS17-PRESSURE"),
  t(762, "2024-09-27T06:20:30Z", "execution_token_issued", "system", "proposal:PRP-PS17-PRESSURE"),
  t(790, "2024-09-27T15:10:44Z", "break_glass_cosigned", "log_01", "proposal:PRP-MUTUAL-AID-0926B"),
  t(1118, "2024-09-28T08:05:30Z", "break_glass_used", "ic_01", "proposal:PRP-CREW-AIK-0928C"),
  t(1119, "2024-09-28T08:05:30Z", "execution_token_issued", "system", "proposal:PRP-CREW-AIK-0928C"),
  t(1174, "2024-09-28T17:36:10Z", "approval_recorded", "plan_etr_01", "proposal:PRP-ETR-GLOBAL-0928"),
  t(1175, "2024-09-28T17:41:02Z", "approval_recorded", "ops_dm_01", "proposal:PRP-ETR-GLOBAL-0928"),
  t(1176, "2024-09-28T17:41:02Z", "execution_token_issued", "system", "proposal:PRP-ETR-GLOBAL-0928"),
  t(1177, "2024-09-28T17:42:15Z", "etr_published", "system", "proposal:PRP-ETR-GLOBAL-0928"),
];

export const review = (broken: number | null): AfterAction => ({
  as_of: AS_OF,
  chain: {
    ok: broken === null,
    checked_to_seq: HEAD_SEQ,
    first_bad_seq: broken,
    signed_head_seq: 1200,
    trusted_to_seq: broken === null ? HEAD_SEQ : broken - 1,
    problems: broken === null ? [] : [`entry ${broken}: fingerprint does not match its content`],
  },
  clocks: [
    {
      decision_case_id: "DC-D1-CREWS-STAGE",
      step: "D1",
      title: "Stage crews at the Aiken yard before 02:15Z",
      effective_decide_by: "2024-09-26T02:15:00Z",
      decided_at: "2024-09-26T01:21:05Z",
      decided_by: "approval",
      proposal_id: "PRP-CREW-AIK-0926A",
      outcome: "met",
      margin_min: 54,
    },
    {
      decision_case_id: "DC-D2-MUTUAL-AID",
      step: "D2",
      title: "Request mutual-aid line crews for the second wave",
      effective_decide_by: "2024-09-26T14:00:00Z",
      decided_at: "2024-09-26T14:36:12Z",
      decided_by: "break_glass",
      proposal_id: "PRP-MUTUAL-AID-0926B",
      outcome: "missed",
      margin_min: -36,
    },
    {
      decision_case_id: "DC-D3-PS17-FUEL",
      step: "D3",
      title: "Send the fuel truck to the PS-17 generator",
      effective_decide_by: "2024-09-27T01:59:00Z",
      decided_at: "2024-09-27T01:12:55Z",
      decided_by: "approval",
      proposal_id: "PRP-PS17-FUEL",
      outcome: "met",
      margin_min: 46,
    },
    {
      decision_case_id: "DC-D3-PS17-POWER",
      step: "D3",
      title: "Restore FDR-AIK-2207 first to power PS-17",
      effective_decide_by: "2024-09-27T03:29:00Z",
      decided_at: "2024-09-27T02:50:41Z",
      decided_by: "approval",
      proposal_id: "PRP-PS17-FDR2207-PRIO",
      outcome: "met",
      margin_min: 38,
    },
    {
      decision_case_id: "DC-D3-PS17-PRESSURE",
      step: "D3",
      title: "Hold pressure in the Cedarfall zone after power returns",
      effective_decide_by: "2024-09-27T05:59:00Z",
      decided_at: "2024-09-27T06:20:30Z",
      decided_by: "approval",
      proposal_id: "PRP-PS17-PRESSURE",
      outcome: "missed",
      margin_min: -21,
    },
    {
      decision_case_id: "DC-D1-CREWS-STAGE-2",
      step: "D1",
      title: "Stage crews at the Aiken yard for the second wave",
      effective_decide_by: "2024-09-28T08:30:00Z",
      decided_at: "2024-09-28T08:05:30Z",
      decided_by: "break_glass",
      proposal_id: "PRP-CREW-AIK-0928C",
      outcome: "met",
      margin_min: 24,
    },
    {
      decision_case_id: "DC-D4-ETR-GLOBAL",
      step: "D4",
      title: "Publish the global restoration estimate",
      effective_decide_by: "2024-09-28T21:30:00Z",
      decided_at: "2024-09-28T17:41:02Z",
      decided_by: "approval",
      proposal_id: "PRP-ETR-GLOBAL-0928",
      outcome: "met",
      margin_min: 229,
    },
    {
      decision_case_id: "DC-D3-BWN-Z3",
      step: "D3",
      title: "Prepare boil-water notice wording for zone Z-3",
      effective_decide_by: "2024-09-28T20:00:00Z",
      decided_at: null,
      decided_by: null,
      proposal_id: null,
      outcome: broken !== null && broken <= 1172 ? "unverifiable" : "open",
      margin_min: null,
    },
  ],
  break_glass: [
    {
      break_glass_id: 1,
      proposal_id: "PRP-MUTUAL-AID-0926B",
      title: "Request mutual-aid line crews for the second wave",
      ic_id: "ic_01",
      tier: "T3",
      reason: "The logistics chief could not be reached before the 14:00Z window; the request had to go out.",
      reason_code: "approver_unreachable",
      used_at: "2024-09-26T14:36:12Z",
      cosign_due: "2024-09-27T14:36:12Z",
      cosigned_by: "log_01",
      cosigned_at: "2024-09-27T15:10:44Z",
      status: "cosigned_late",
      table_agrees: true,
    },
    {
      break_glass_id: 2,
      proposal_id: "PRP-CREW-AIK-0928C",
      title: "Stage crews at the Aiken yard for the second wave",
      ic_id: "ic_01",
      tier: "T3",
      reason: "Yard access closed at 08:40Z; staging had to be ordered before the road closure.",
      reason_code: "time_critical",
      used_at: "2024-09-28T08:05:30Z",
      cosign_due: "2024-09-29T08:05:30Z",
      cosigned_by: null,
      cosigned_at: null,
      status: "awaiting_cosign",
      table_agrees: true,
    },
  ],
  timeline,
  scorecard: scorecard as Scorecard,
  sc_report: scReport as unknown as ScReport,
});

const verifyResult = (broken: number | null): AuditVerifyResult => ({
  ok: broken === null,
  checked_to_seq: HEAD_SEQ,
  first_bad_seq: broken,
  signed_head_seq: 1200,
  notary: "signed",
});

/** The demo edits entry 702 of a copy; the "real" mock chain stays intact. */
export const TAMPERED_SEQ = 702;

export const handlers = [
  http.get("/api/after-action", async () => {
    await delay(40);
    return HttpResponse.json(review(brokenAt()));
  }),
  http.post("/api/audit/verify", async () => {
    await delay(300);
    return HttpResponse.json(verifyResult(brokenAt()));
  }),
  http.post("/api/audit/tamper-demo", async () => {
    await delay(300);
    const body: TamperDemo = {
      tampered_seq: TAMPERED_SEQ,
      untrusted_from_seq: TAMPERED_SEQ,
      result: verifyResult(TAMPERED_SEQ),
    };
    return HttpResponse.json(body);
  }),
];
