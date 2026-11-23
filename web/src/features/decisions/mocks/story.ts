import { NUMBERS } from "@/contracts/numbers.gen";
import { POLICIES } from "@/contracts/policies.gen";
import type { ApprovalFunction, UiSeverity } from "@/contracts/vocab.gen";
import type { AuditEvent, PolicyParam, ProposalCard, ProposalSummary } from "@/lib/api";
import { OPEN_STATES } from "../severity";

export type Advisory = "N" | "N+1";

/** Scenario time at each advisory of the PS-17 story (K16 hinge: advisory N at 09:00Z, N+1 at 15:00Z on 26 Sep 2024). */
export const ADVISORY_TIME: Record<Advisory, string> = {
  N: "2024-09-26T09:30:00Z",
  "N+1": "2024-09-26T15:25:00Z",
};

const DAY_AFTER = Date.parse("2024-09-27T00:00:00Z");
const atMin = (minutesAfterMidnight: number) =>
  new Date(DAY_AFTER + minutesAfterMidnight * 60_000).toISOString();
const MIN = 60_000;
const iso = (ms: number) => new Date(ms).toISOString().replace(".000Z", "Z");

const PS17_LEAD = NUMBERS.demo_ps17_generator_lead_min.value;
const CREWS_LEAD = 300;
const PS17_DECIDE: Record<Advisory, string> = {
  N: atMin(NUMBERS.demo_ps17_decide_by_n_min.value),
  "N+1": atMin(NUMBERS.demo_ps17_decide_by_n1_min.value),
};
const CREWS_OWN: Record<Advisory, string> = { N: "2024-09-27T01:10:00Z", "N+1": "2024-09-26T23:50:00Z" };
const PS17_SHARE: Record<Advisory, number> = { N: 640_000, "N+1": 910_000 };

/** Stand-in for the server rule (`sgw.approval.severity`): the mock API sends severity, the UI never works it out. */
function mockSeverity(c: ProposalCard, now: string): UiSeverity {
  if (!OPEN_STATES.has(c.state)) return "normal";
  const min = (Date.parse(c.effective_decide_by_utc) - Date.parse(now)) / 60_000;
  if (min < 0) return "critical";
  if (min < 60) return "severe";
  return c.on_critical_path || min < 360 ? "elevated" : "advisory";
}

const hash = (seed: string) =>
  seed
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "")
    .padEnd(64, "0")
    .slice(0, 64);

interface ClockInput {
  decideBy: string;
  lead: number;
  basis: { id: string; cite: string | null };
  leadBasis: { id: string; cite: string | null };
  ifLate: string;
}

function clockFor({ decideBy, lead, basis, leadBasis, ifLate }: ClockInput) {
  const decide = Date.parse(decideBy);
  const consequence = decide + lead * MIN;
  return {
    decide_by_utc: decideBy,
    decide_by_p10_utc: iso(decide - 45 * MIN),
    decide_by_p90_utc: iso(decide + 50 * MIN),
    consequence_utc: iso(consequence),
    consequence_p10_utc: iso(consequence - 45 * MIN),
    consequence_p90_utc: iso(consequence + 50 * MIN),
    consequence_basis: {
      kind: "model_estimate" as const,
      basis_id: basis.id,
      basis_version: "0.1-synthetic",
      citation: basis.cite,
    },
    action_lead_time_min: lead,
    lead_time_basis: {
      kind: "model_estimate" as const,
      basis_id: leadBasis.id,
      basis_version: "0.1-synthetic",
      citation: leadBasis.cite,
    },
    clock_kind: "model_estimate" as const,
    if_late: ifLate,
  };
}

interface Seed {
  id: string;
  caseId: string;
  title: string;
  action: ProposalCard["action_type"];
  tier: ProposalCard["tier"];
  step: ProposalCard["case"]["step"];
  domain: "electric" | "water";
  decideBy: string;
  effective: string;
  lead: number;
  path: boolean;
  verdict: ProposalCard["case"]["no_regret_verdict"];
  sharePpm: number | null;
  functions: ApprovalFunction[];
  rationale: string;
  basis: ClockInput["basis"];
  leadBasis: ClockInput["leadBasis"];
  ifLate: string;
  prerequisites?: string[];
  targets: string[];
  params?: Record<string, unknown>;
  preconditions?: Record<string, boolean>;
  escalators?: string[];
  proposer: ProposalCard["proposed_by"];
  evidence?: string[];
}

const person = (
  user_id: string,
  display_name: string,
  fn: ApprovalFunction,
): ProposalCard["proposed_by"] => ({
  user_id,
  display_name,
  function: fn,
  initiator_kind: "person",
});

const SC_AIKEN = "SC-45003";

function seeds(adv: Advisory): Seed[] {
  const ps17Effective = PS17_DECIDE[adv];
  const crewsEffective = iso(
    Math.min(Date.parse(CREWS_OWN[adv]), Date.parse(ps17Effective) - CREWS_LEAD * MIN),
  );
  const n1 = adv === "N+1";
  return [
    {
      id: "PRP-PS17-FDR2207-PRIO",
      caseId: "DC-D3-PS17-POWER",
      title: "Restore FDR-AIK-2207 first to power PS-17",
      action: "cross_domain_priority",
      tier: "T3",
      step: "D3",
      domain: "water",
      decideBy: ps17Effective,
      effective: ps17Effective,
      lead: PS17_LEAD,
      path: true,
      verdict: n1 ? "act_now" : "wait_for_next_advisory",
      sharePpm: PS17_SHARE[adv],
      functions: ["command", "water_operations"],
      rationale: n1
        ? "Synthetic data. Advisory N+1 moves tropical-storm wind onset at Aiken earlier. PS-17 holds hospital pressure and has no generator on site. Feeder FDR-AIK-2207 is the faster route to restoring PS-17 power."
        : "Synthetic data. Feeder FDR-AIK-2207 powers pump station PS-17, which holds hospital pressure. Acting now is not regretted in most scenarios, but the next advisory arrives before the deadline.",
      basis: { id: "water_twin.ps17_pressure_floor", cite: "SC R.61-58.7.E(7) 25 psi floor" },
      leadBasis: { id: "lead_time.portable_generator_hookup", cite: "SOP-WTR-4.2" },
      ifLate: "Hospital zone pressure falls below the 25 psi floor before a generator is running at PS-17.",
      prerequisites: ["DC-D2-CREWS-AIK"],
      targets: ["PS-17", "FDR-AIK-2207"],
      params: { restore_first: "FDR-AIK-2207", restore_after: "FDR-AIK-2301", portable_generator_kw: 500 },
      preconditions: { hospital_on_own_generator: true, ps17_onsite_generator: false },
      escalators: ["critical_facility", "cross_domain"],
      proposer: {
        user_id: "system:rule:ps17_pressure_floor",
        display_name: "Pressure-floor rule",
        function: null,
        initiator_kind: "system_rule",
      },
      evidence: ["EV-PS17-PRESSURE-0926", "EV-HOSP-STORAGE-0926"],
    },
    {
      id: "PRP-CREW-AIK-0926A",
      caseId: "DC-D2-CREWS-AIK",
      title: "Pre-position crews at Sandhill and Millpond yards before tropical-storm winds",
      action: "preposition_crews",
      tier: "T3",
      step: "D2",
      domain: "electric",
      decideBy: CREWS_OWN[adv],
      effective: crewsEffective,
      lead: CREWS_LEAD,
      path: true,
      verdict: "n/a",
      sharePpm: null,
      functions: ["command", "logistics"],
      rationale: `Synthetic data. Advisory ${adv} puts tropical-storm wind onset at the Millpond yard at ${n1 ? "04:50" : "06:10"} UTC on 27 Sep; crews need five hours to mobilise and stage.`,
      basis: { id: "hazard.ts_wind_onset", cite: null },
      leadBasis: { id: "lead_time.crew_mobilise_and_stage", cite: "SOP-ELE-2.1" },
      ifLate: "Crews travel into tropical-storm winds or arrive after the first feeder trips.",
      targets: ["STG-AIK-SANDHILL-YARD", "STG-RCH-MILLPOND-YARD"],
      params: {
        envelope_pct: 20,
        "crews_at_STG-AIK-SANDHILL-YARD": n1 ? 18 : 14,
        "crews_at_STG-RCH-MILLPOND-YARD": 9,
      },
      preconditions: { roads_open_to_yards: true, mutual_aid_confirmed: false },
      escalators: ["helene_scale", "targets_gt_10_or_cost"],
      proposer: person("ops_dm_01", "Duty Manager, Electric Operations", "operations"),
    },
    {
      id: "PRP-AIK-STAGE",
      caseId: "DC-D2-STAGE-AIK",
      title: "Stage a small crew at the Aiken yard",
      action: "stage_crews_small",
      tier: "T2",
      step: "D2",
      domain: "electric",
      decideBy: "2024-09-26T09:55:00Z",
      effective: "2024-09-26T09:55:00Z",
      lead: 90,
      path: false,
      verdict: "decide_now",
      sharePpm: 960_000,
      functions: ["operations"],
      rationale:
        "Synthetic data. A small crew staged now can reach the feeder before wind exceeds the bucket limit.",
      basis: { id: "hazard.bucket_wind_limit", cite: null },
      leadBasis: { id: "lead_time.small_crew_staging", cite: "SOP-ELE-2.4" },
      ifLate: "The crew cannot work aloft once wind passes the bucket limit.",
      targets: ["STG-AIK-SANDHILL-YARD"],
      params: { crews: 2 },
      preconditions: { roads_open_to_yards: true },
      proposer: person("plan_etr_01", "ETR Specialist", "planning"),
    },
    {
      id: "PRP-MUTUAL-AID",
      caseId: "DC-D1-MUTUAL-AID",
      title: "Request mutual-aid line crews for the second wave",
      action: "mutual_aid_request",
      tier: "T2",
      step: "D1",
      domain: "electric",
      decideBy: "2024-09-26T20:30:00Z",
      effective: "2024-09-26T20:30:00Z",
      lead: 240,
      path: false,
      verdict: "decide_now",
      sharePpm: 880_000,
      functions: ["logistics"],
      rationale: "Synthetic data. Mutual aid takes hours to arrive; asking early costs little.",
      basis: { id: "hazard.second_wave_onset", cite: null },
      leadBasis: { id: "lead_time.mutual_aid_arrival", cite: "SOP-LOG-1.2" },
      ifLate: "Mutual-aid crews arrive after the second wave has started.",
      targets: [],
      proposer: person("log_01", "Logistics Section Chief", "logistics"),
    },
    {
      id: "PRP-BWN-READY",
      caseId: "DC-D4-BWN-READY",
      title: "Prepare boil-water notice wording for zone Z-3",
      action: "boil_water_notice",
      tier: "T3",
      step: "D4",
      domain: "water",
      decideBy: "2024-09-27T07:30:00Z",
      effective: "2024-09-27T07:30:00Z",
      lead: 120,
      path: false,
      verdict: "wait_for_next_advisory",
      sharePpm: 500_000,
      functions: ["water_operations", "compliance"],
      rationale: "Synthetic data. A notice is only needed if pressure drops; the next advisory narrows this.",
      basis: { id: "water_twin.zone_pressure", cite: "SC R.61-58.7.E(7)" },
      leadBasis: { id: "lead_time.notice_issue", cite: "SGW WQC 07.120 Rev C section 6.3.3" },
      ifLate: "The written notice reaches customers later than the rule allows.",
      targets: ["PS-17"],
      proposer: person("wtr_lead_01", "Water Incident Lead", "water_operations"),
    },
    {
      id: "PRP-SITREP-PRELANDFALL",
      caseId: "DC-D5-SITREP",
      title: "Publish the pre-landfall situation report",
      action: "sitrep_draft",
      tier: "T1",
      step: "D5",
      domain: "electric",
      decideBy: "2024-09-27T04:00:00Z",
      effective: "2024-09-27T04:00:00Z",
      lead: 30,
      path: false,
      verdict: "n/a",
      sharePpm: null,
      functions: ["command"],
      rationale: "Synthetic data. Routine report on the current plan.",
      basis: { id: "schedule.sitrep_cycle", cite: null },
      leadBasis: { id: "lead_time.sitrep_review", cite: null },
      ifLate: "Partners work from an out-of-date report.",
      targets: [],
      proposer: person("ic_01", "Incident Commander", "command"),
    },
  ];
}

export const ENVELOPE_BOUNDS = {
  "crews_at_STG-AIK-SANDHILL-YARD": { min: 15, max: 21 },
  "crews_at_STG-RCH-MILLPOND-YARD": { min: 8, max: 10 },
};

export function buildStoryCard(seed: Seed, adv: Advisory): ProposalCard {
  const crewsV1Signed = seed.id === "PRP-CREW-AIK-0926A" && adv === "N";
  const crewsV2 = seed.id === "PRP-CREW-AIK-0926A" && adv === "N+1";
  const stageDone = seed.id === "PRP-AIK-STAGE" && adv === "N+1";
  const card: ProposalCard = {
    proposal_id: seed.id,
    decision_case_id: seed.caseId,
    action_type: seed.action,
    title: seed.title,
    tier: seed.tier,
    state: stageDone ? "approved" : crewsV1Signed ? "in_review" : "in_review",
    proposal_version: crewsV2 ? 2 : 1,
    action_hash: hash(`${seed.id}${crewsV2 ? "v2" : "v1"}`),
    decide_by_utc: seed.decideBy,
    effective_decide_by_utc: seed.effective,
    on_critical_path: seed.path,
    functions_required: seed.functions,
    approvals: crewsV1Signed
      ? [{ approver_id: "ic_01", function: "command", decision: "approve", at: "2024-09-26T09:12:00Z" }]
      : stageDone
        ? [
            {
              approver_id: "ops_dm_01",
              function: "operations",
              decision: "approve",
              at: "2024-09-26T09:40:00Z",
            },
          ]
        : [],
    expires_at: null,
    case: {
      decision_case_id: seed.caseId,
      step: seed.step,
      title: seed.title,
      domain: seed.domain,
      region_id: SC_AIKEN,
      clock: clockFor({
        decideBy: seed.decideBy,
        lead: seed.lead,
        basis: seed.basis,
        leadBasis: seed.leadBasis,
        ifLate: seed.ifLate,
      }),
      prerequisite_ids: seed.prerequisites ?? [],
      blocked_by: seed.prerequisites ?? [],
      effective_decide_by_utc: seed.effective,
      on_critical_path: seed.path,
      no_regret_share_ppm: seed.sharePpm,
      no_regret_verdict: seed.verdict,
      next_advisory_utc: adv === "N" ? "2024-09-26T15:00:00Z" : "2024-09-26T21:00:00Z",
    },
    params: seed.params ?? {},
    target_ids: seed.targets,
    preconditions: seed.preconditions ?? {},
    escalators: seed.escalators ?? [],
    evidence_ids: seed.evidence ?? [],
    rationale: seed.rationale,
    policy_version: "policy-2026.11.19-w0",
    envelope: null,
    break_glass: null,
    changes_since_version: crewsV2 ? ["crews_at_STG-AIK-SANDHILL-YARD"] : [],
    severity: "normal",
    proposed_by: seed.proposer,
    owner_function: seed.proposer.function ?? seed.functions[0] ?? null,
  };
  card.severity = mockSeverity(card, ADVISORY_TIME[adv]);
  return card;
}

export const storyCards = (adv: Advisory): ProposalCard[] => seeds(adv).map((s) => buildStoryCard(s, adv));

export function summaryOf(c: ProposalCard): ProposalSummary {
  return {
    proposal_id: c.proposal_id,
    decision_case_id: c.decision_case_id,
    action_type: c.action_type,
    title: c.title,
    tier: c.tier,
    state: c.state,
    proposal_version: c.proposal_version,
    action_hash: c.action_hash,
    decide_by_utc: c.decide_by_utc,
    effective_decide_by_utc: c.effective_decide_by_utc,
    on_critical_path: c.on_critical_path,
    functions_required: c.functions_required,
    approvals: c.approvals,
    expires_at: c.expires_at,
    severity: c.severity,
    proposed_by: c.proposed_by,
    owner_function: c.owner_function,
  } as ProposalSummary;
}

export function auditFor(cards: ProposalCard[]): AuditEvent[] {
  const out: AuditEvent[] = [];
  let seq = 1;
  const push = (
    e: Omit<
      AuditEvent,
      "stream" | "seq" | "payload_hash" | "prev_hash" | "hash" | "actor_type" | "decision" | "reason"
    > & {
      actor_type?: AuditEvent["actor_type"];
      decision?: string | null;
      reason?: string | null;
    },
  ) =>
    out.push({
      stream: "global",
      seq: seq++,
      payload_hash: "0".repeat(64),
      prev_hash: "0".repeat(64),
      hash: "0".repeat(64),
      actor_type: "user",
      decision: null,
      reason: null,
      ...e,
    });
  for (const c of cards) {
    for (const a of c.approvals) {
      push({ occurred_at: a.at, actor_id: a.approver_id, kind: "approval_recorded", subject: c.proposal_id });
    }
  }
  return out;
}

export const policyParams = (): PolicyParam[] =>
  Object.entries(POLICIES).map(
    ([key, p]) =>
      ({
        key,
        value: p.value,
        unit: p.unit,
        label: p.label,
        kind: "policy",
        chip: p.chip,
        source: p.source,
      }) as PolicyParam,
  );

export interface StoryContext {
  cards: ProposalCard[];
  scenario: { scenario_time: string };
  emit: (eventType: string, payload: object, scenarioTime: string) => void;
}

/** Moves the mock world from one advisory to the next the way the golden stream does, and announces it on the ops stream. */
export function advanceStory(adv: Advisory, ctx: StoryContext): void {
  const prev = new Map(ctx.cards.map((c) => [c.proposal_id, c]));
  const next = storyCards(adv).map((card) => {
    const before = prev.get(card.proposal_id);
    if (!before) return card;
    if (before.proposal_version !== card.proposal_version) return card;
    const closing = card.state === "approved" && before.state !== "approved";
    return {
      ...card,
      approvals: closing ? card.approvals : before.approvals,
      state: closing ? card.state : before.state,
      envelope: before.envelope,
      break_glass: before.break_glass,
    };
  });
  const at = ADVISORY_TIME[adv];
  ctx.scenario.scenario_time = at;
  ctx.cards.splice(0, ctx.cards.length, ...next);
  ctx.emit("ScenarioClockChanged", { bookmark: "H0-24", scenario_time_utc: at, speed: 0 }, at);
  for (const card of next) {
    const before = prev.get(card.proposal_id);
    if (!before) continue;
    if (before.effective_decide_by_utc !== card.effective_decide_by_utc) {
      ctx.emit(
        "DecisionClockUpdated",
        {
          decision_case_id: card.decision_case_id,
          decide_by_utc: card.decide_by_utc,
          effective_decide_by_utc: card.effective_decide_by_utc,
          no_regret_verdict: card.case.no_regret_verdict,
          on_critical_path: card.on_critical_path,
          previous_decide_by_utc: before.effective_decide_by_utc,
        },
        at,
      );
    }
    if (before.proposal_version !== card.proposal_version) {
      ctx.emit(
        "ProposalUpdated",
        {
          proposal_id: card.proposal_id,
          proposal_version: card.proposal_version,
          action_hash: card.action_hash,
          changed_fields: ["params"],
          decide_by_utc: card.decide_by_utc,
          material: true,
          reason: `Advisory ${adv}: crews at STG-AIK-SANDHILL-YARD 14 -> 18`,
          voided_approval_ids: before.approvals.map((a) => `APR-${a.approver_id}`),
        },
        at,
      );
    }
  }
}

/** Switches the mock world to the PS-17 story at the given advisory and tells every open page to reload its data. */
export function startStory(adv: Advisory, ctx: StoryContext): void {
  const at = ADVISORY_TIME[adv];
  ctx.scenario.scenario_time = at;
  ctx.cards.splice(0, ctx.cards.length, ...storyCards(adv));
  ctx.emit("resync", { epoch: 2, reason: "epoch_mismatch", snapshot_url: "/api/proposals" }, at);
}
