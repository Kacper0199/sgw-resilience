import { PERSONAS } from "@/auth/personas";
import { EXAMPLES } from "@/contracts/msw.gen";
import { SEVERITY_VECTORS } from "@/contracts/vectors.gen";
import type {
  Asset,
  ClockWaterfall,
  Me,
  ProposalCard,
  ProposalSummary,
  Region,
  ScenarioState,
} from "@/lib/api";

export const MOCK_NOW = "2024-09-27T01:00:00Z";

const ADVISORY_TIMES = [
  "2024-09-24T15:00:00Z",
  "2024-09-24T21:00:00Z",
  "2024-09-25T03:00:00Z",
  "2024-09-25T09:00:00Z",
  "2024-09-25T15:00:00Z",
  "2024-09-25T21:00:00Z",
  "2024-09-26T03:00:00Z",
  "2024-09-26T09:00:00Z",
  "2024-09-26T15:00:00Z",
  "2024-09-26T21:00:00Z",
  "2024-09-27T03:00:00Z",
  "2024-09-27T09:00:00Z",
];

/** The Helene replay as `GET /api/scenario` serves it: period, key moments and the presenter's jumps. */
export const scenario: ScenarioState = {
  ...(EXAMPLES.getScenario as unknown as ScenarioState),
  scenario: "helene",
  scenario_time: MOCK_NOW,
  speed: 0,
  loads_moments: true,
  phases: [
    { phase: "before_landfall", label: "Before landfall", starts_utc: "2024-09-23T12:00:00Z" },
    { phase: "storm", label: "Storm", starts_utc: "2024-09-27T03:10:00Z" },
    { phase: "restoration", label: "Restoration", starts_utc: "2024-09-27T14:00:00Z" },
    { phase: "recovery", label: "Recovery", starts_utc: "2024-10-06T02:00:00Z" },
  ],
  final_advisory_utc: "2024-09-27T09:00:00Z",
  window_start: "2024-09-23T12:00:00Z",
  window_end: "2024-10-06T12:00:00Z",
  period: {
    title: "Hurricane Helene",
    start_utc: "2024-09-23T12:00:00Z",
    end_utc: "2024-10-06T12:00:00Z",
    time_zone: "America/New_York",
    label: "23 Sep – 6 Oct 2024",
    data_note: "Synthetic SGW utility data on the real storm's track and weather",
    statement:
      "Scenario period: a replay of Hurricane Helene from 23 Sep 2024 08:00 ET to 6 Oct 2024 08:00 ET, with synthetic SGW utility data. Every time in the platform is a scenario time inside this period; never compare it with today's date.",
  },
  moments: [
    ...ADVISORY_TIMES.map((t, i) => ({
      moment_id: `advisory-${i + 1}`,
      kind: "advisory" as const,
      label: "Advisory",
      scenario_time: t,
    })),
    { moment_id: "landfall", kind: "landfall", label: "Landfall", scenario_time: "2024-09-27T03:10:00Z" },
    { moment_id: "peak", kind: "peak", label: "Peak outages", scenario_time: "2024-09-27T14:00:00Z" },
  ],
  jumps: [
    {
      moment_id: "before-n",
      kind: "demo",
      label: "Before the 5 AM advisory",
      scenario_time: "2024-09-26T08:00:00Z",
    },
    { moment_id: "at-n", kind: "demo", label: "5 AM advisory", scenario_time: "2024-09-26T09:05:00Z" },
    {
      moment_id: "at-n1",
      kind: "demo",
      label: "11 AM advisory: deadlines move",
      scenario_time: "2024-09-26T15:05:00Z",
    },
    {
      moment_id: "morning-after",
      kind: "demo",
      label: "Morning after landfall",
      scenario_time: "2024-09-27T12:00:00Z",
    },
    {
      moment_id: "etr-published",
      kind: "demo",
      label: "Restoration estimate published",
      scenario_time: "2024-09-28T18:00:00Z",
    },
    {
      moment_id: "notices-lifted",
      kind: "demo",
      label: "Boil-water notices lifted",
      scenario_time: "2024-09-30T12:00:00Z",
    },
    {
      moment_id: "after-action",
      kind: "demo",
      label: "After-action review",
      scenario_time: "2024-10-06T02:00:00Z",
    },
  ],
};

export const regions: Region[] = [
  {
    region_id: "SC-AIK",
    state: "SC",
    county_fips: "45003",
    name: "Aiken",
    bbox_e6: [-82_030_000, 33_210_000, -81_120_000, 33_830_000],
  },
  {
    region_id: "GA-RIC",
    state: "GA",
    county_fips: "13245",
    name: "Richmond",
    bbox_e6: [-82_360_000, 33_210_000, -81_840_000, 33_520_000],
  },
];

export const assets: Asset[] = [
  {
    asset_id: "PS-17",
    name: "PS-17 Cedarfall booster (synthetic)",
    domain: "water",
    kind: "pump_station",
    region_id: "SC-AIK",
    lon_e6: -81_720_000,
    lat_e6: 33_560_000,
    criticality: null,
    critical_facility: true,
    customers_served: 18000,
    classification: "C1",
  },
  {
    asset_id: "FDR-AIK-2207",
    name: "Feeder FDR-AIK-2207 (synthetic)",
    domain: "electric",
    kind: "feeder",
    region_id: "SC-AIK",
    lon_e6: -81_650_000,
    lat_e6: 33_610_000,
    criticality: null,
    critical_facility: false,
    customers_served: 6200,
    classification: "C1",
  },
];

export function meFor(userId: string): Me | null {
  const p = PERSONAS.find((x) => x.user_id === userId);
  if (!p) return null;
  return {
    user_id: p.user_id,
    display_name: p.title,
    function: p.function,
    roles: [],
    regions: ["SC", "GA"],
    domains: ["electric", "water"],
    step_up_valid_until: null,
    demo_mode: true,
  };
}

const clockFor = (decideBy: string, lead: number) => {
  const decide = Date.parse(decideBy);
  const consequence = new Date(decide + lead * 60_000).toISOString();
  return {
    decide_by_utc: decideBy,
    decide_by_p10_utc: new Date(decide - 25 * 60_000).toISOString(),
    decide_by_p90_utc: new Date(decide + 25 * 60_000).toISOString(),
    consequence_utc: consequence,
    consequence_p10_utc: new Date(Date.parse(consequence) - 25 * 60_000).toISOString(),
    consequence_p90_utc: new Date(Date.parse(consequence) + 25 * 60_000).toISOString(),
    consequence_basis: {
      kind: "model_estimate" as const,
      basis_id: "water_twin.ps17_pressure_floor",
      basis_version: "0.1-synthetic",
      citation: null,
    },
    action_lead_time_min: lead,
    lead_time_basis: {
      kind: "model_estimate" as const,
      basis_id: "lead_time.portable_generator_hookup",
      basis_version: "0.1-synthetic",
      citation: null,
    },
    clock_kind: "model_estimate" as const,
    if_late: "Pressure falls below the floor.",
  };
};

interface Seed {
  id: string;
  caseId: string;
  title: string;
  action: ProposalCard["action_type"];
  tier: ProposalCard["tier"];
  domain: "electric" | "water";
  decideBy: string;
  lead: number;
  path: boolean;
  verdict: ProposalCard["case"]["no_regret_verdict"];
  functions: ProposalCard["functions_required"];
  rationale: string;
  targets?: string[];
  prerequisites?: string[];
}

const SEEDS: Seed[] = [
  {
    id: "PRP-PS17-FDR2207-PRIO",
    caseId: "DC-D3-PS17-POWER",
    title: "Restore FDR-AIK-2207 first to power PS-17",
    action: "cross_domain_priority",
    tier: "T3",
    domain: "water",
    decideBy: "2024-09-27T04:10:00Z",
    lead: 150,
    path: true,
    verdict: "act_now",
    functions: ["command", "water_operations"],
    rationale: "Feeder FDR-AIK-2207 powers pump station PS-17, which holds hospital pressure.",
    targets: ["FDR-AIK-2207", "PS-17", "HSP-AIK-TALLOWBRANCH"],
    prerequisites: ["DC-D2-CREWS-AIK"],
  },
  {
    id: "PRP-AIK-STAGE",
    caseId: "DC-D2-CREWS-AIK",
    title: "Stage crews at the Aiken yard before 02:15Z",
    action: "stage_crews_small",
    tier: "T2",
    domain: "electric",
    decideBy: "2024-09-27T01:40:00Z",
    lead: 90,
    path: false,
    verdict: "act_now",
    functions: ["operations"],
    rationale: "Crews staged now can reach the feeder before wind exceeds the bucket limit.",
    targets: ["STG-AIK-SANDHILL-YARD"],
  },
  {
    id: "PRP-BWN-READY",
    caseId: "DC-D4-BWN-READY",
    title: "Prepare boil-water notice wording for zone Z-3",
    action: "boil_water_notice",
    tier: "T3",
    domain: "water",
    decideBy: "2024-09-27T09:30:00Z",
    lead: 120,
    path: false,
    verdict: "wait_for_next_advisory",
    functions: ["water_operations", "compliance"],
    rationale: "A notice is only needed if pressure drops; the next advisory narrows this.",
  },
  {
    id: "PRP-MUTUAL-AID",
    caseId: "DC-D1-MUTUAL-AID",
    title: "Request mutual-aid line crews for the second wave",
    action: "mutual_aid_request",
    tier: "T2",
    domain: "electric",
    decideBy: "2024-09-27T07:00:00Z",
    lead: 240,
    path: false,
    verdict: "decide_now",
    functions: ["logistics"],
    rationale: "Mutual aid takes hours to arrive; asking early costs little.",
  },
  {
    id: "PRP-SITREP-0900",
    caseId: "DC-D5-SITREP",
    title: "Publish the 09:00Z situation report",
    action: "sitrep_draft",
    tier: "T1",
    domain: "electric",
    decideBy: "2024-09-27T08:30:00Z",
    lead: 30,
    path: false,
    verdict: "n/a",
    functions: ["command"],
    rationale: "Routine report on the current plan.",
  },
];

const RULE_PROPOSER: ProposalCard["proposed_by"] = {
  user_id: "system:rule:ps17_pressure_floor",
  display_name: "SGW rule ps17_pressure_floor",
  function: null,
  initiator_kind: "system_rule",
};

const DUTY_MANAGER: ProposalCard["proposed_by"] = {
  user_id: "ops_dm_01",
  display_name: "Duty Manager, Electric Operations",
  function: "operations",
  initiator_kind: "person",
};

/** Severity the server rule gives each mock proposal at MOCK_NOW (generated by `uv run sgw contracts`). */
export function serverSeverity(proposalId: string): ProposalCard["severity"] {
  const found = SEVERITY_VECTORS.cases.find((c) => c.id === proposalId);
  if (!found)
    throw new Error(`no server severity vector for ${proposalId}; add it to MOCK_QUEUE in export.py`);
  return found.severity;
}

export function buildCard(seed: Seed): ProposalCard {
  const proposedBy = seed.domain === "water" ? RULE_PROPOSER : DUTY_MANAGER;
  return {
    proposal_id: seed.id,
    decision_case_id: seed.caseId,
    action_type: seed.action,
    title: seed.title,
    tier: seed.tier,
    state: "in_review",
    proposal_version: 1,
    action_hash:
      `${seed.id.toLowerCase().replace(/[^a-z0-9]/g, "")}0000000000000000000000000000000000000000000000`.slice(
        0,
        64,
      ),
    decide_by_utc: seed.decideBy,
    effective_decide_by_utc: seed.decideBy,
    on_critical_path: seed.path,
    functions_required: seed.functions,
    approvals: [],
    expires_at: null,
    severity: serverSeverity(seed.id),
    proposed_by: proposedBy,
    owner_function: proposedBy.function ?? seed.functions[0] ?? null,
    case: {
      decision_case_id: seed.caseId,
      step: "D3",
      title: seed.title,
      domain: seed.domain,
      region_id: "SC-AIK",
      clock: clockFor(seed.decideBy, seed.lead),
      effective_decide_by_utc: seed.decideBy,
      on_critical_path: seed.path,
      no_regret_share_ppm: seed.verdict === "act_now" ? 925_000 : null,
      no_regret_verdict: seed.verdict,
      next_advisory_utc: "2024-09-27T03:00:00Z",
      prerequisite_ids: seed.prerequisites ?? [],
    },
    params: {},
    target_ids: seed.targets ?? (seed.domain === "water" ? ["PS-17"] : ["FDR-AIK-2207"]),
    preconditions: {},
    escalators: [],
    evidence_ids: [],
    rationale: seed.rationale,
    policy_version: "policy-0.1-synthetic",
    envelope: null,
    break_glass: null,
  };
}

export const freshCards = (): ProposalCard[] => SEEDS.map(buildCard);

export const toSummary = (c: ProposalCard): ProposalSummary => ({
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
});

export const toWaterfall = (c: ProposalCard): ClockWaterfall => ({
  decision_case_id: c.decision_case_id,
  consequence_utc: c.case.clock.consequence_utc,
  consequence_range_utc: [c.case.clock.consequence_p10_utc, c.case.clock.consequence_p90_utc],
  consequence_basis: c.case.clock.consequence_basis,
  action_lead_time_min: c.case.clock.action_lead_time_min,
  lead_time_basis: c.case.clock.lead_time_basis,
  decide_by_utc: c.decide_by_utc,
  effective_decide_by_utc: c.effective_decide_by_utc,
  bound_by_case_id: null,
});
