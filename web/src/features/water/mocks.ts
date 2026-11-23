import { delay, HttpResponse, http } from "msw";
import { POLICIES } from "@/contracts/policies.gen";
import type { ProposalCard } from "@/lib/api";
import { assets, MOCK_NOW } from "@/mocks/fixtures";
import anomalyReport from "./mocks/anomaly-report.json";
import advisories from "./mocks/register.json";
import rules from "./mocks/rules.json";
import type { AnomalyItem, BwaAdvisory, WaterZone } from "./types";

const ASOF_KEY = "sgw.mock.anomalies_asof";
const ZONE_RULES_KEY = "sgw.mock.zone_rules";

/** `sessionStorage["sgw.mock.zone_rules"] = "1"` puts the mock at the morning after landfall with the zone rules on: four zones at four stages of the boil-water lifecycle. */
const zoneRulesOn = (): boolean =>
  typeof sessionStorage !== "undefined" && sessionStorage.getItem(ZONE_RULES_KEY) === "1";

/** Seeded Helene replay: four pump-station zones, full tanks on grid power at the mock clock (62 psi); PS-38 and PS-52 have their own standby generators. */
export const zones: WaterZone[] = [
  {
    zone_id: "WZ-PS17-CEDARFALL",
    pump_station_id: "PS-17",
    pressure_psi_x10: 620,
    floor_psi_x10: 250,
    critical_facility_ids: ["HSP-AIK-TALLOWBRANCH"],
    on_backup_power: false,
  },
  {
    zone_id: "WZ-PS23-LAURELSPUR",
    pump_station_id: "PS-23",
    pressure_psi_x10: 620,
    floor_psi_x10: 250,
    critical_facility_ids: [],
    on_backup_power: false,
  },
  {
    zone_id: "WZ-PS38-COPPERLEAF",
    pump_station_id: "PS-38",
    pressure_psi_x10: 620,
    floor_psi_x10: 250,
    critical_facility_ids: [],
    on_backup_power: false,
    onsite_generator_id: "GEN-PS38-COPPERLEAF",
    generator_state: null,
  },
  {
    zone_id: "WZ-PS52-DEERWATER",
    pump_station_id: "PS-52",
    pressure_psi_x10: 620,
    floor_psi_x10: 250,
    critical_facility_ids: [],
    on_backup_power: false,
    onsite_generator_id: "GEN-PS52-DEERWATER",
    generator_state: null,
  },
];

/** Alarms the anomaly detectors raised on the Helene replay (`data/artefacts/water_twin/anomaly_dev.json`). */
export const replayAnomalies: AnomalyItem[] = [
  ["PS-17", "PT-PS17-DISCH", "pressure_loss", "2024-09-27T09:00:00Z"],
  ["PS-23", "PT-PS23-DISCH", "pressure_loss", "2024-09-27T09:30:00Z"],
  ["PS-17", "LT-TNK-PS17-CEDARFALL", "demand_increase", "2024-09-27T11:00:00Z"],
].map(([, entity, cls, at], i) => ({
  anomaly_id: `ANM-REPLAY-${i + 1}`,
  entity_id: entity as string,
  detected_at: at as string,
  score_ppm: 1_000_000,
  anomaly_class: cls as string,
  status: "open",
}));

const asOf = (): string =>
  (typeof sessionStorage === "undefined" ? null : sessionStorage.getItem(ASOF_KEY)) ?? MOCK_NOW;

export const waterAssets = [
  ...assets,
  ...["GEN-PS38-COPPERLEAF", "GEN-PS52-DEERWATER", "GEN-HSP-TALLOWBRANCH", "MGEN-HALBERD-500"].map(
    (id, i) => ({
      asset_id: id,
      domain: "water" as const,
      kind: id.startsWith("MGEN") ? "portable_generator" : "generator",
      region_id: "SC-AIK",
      lon_e6: -81_700_000 - i * 20_000,
      lat_e6: 33_500_000 + i * 30_000,
      criticality: id.includes("HSP") ? 5 : 4,
      critical_facility: id.includes("HSP"),
      customers_served: id.includes("HSP") ? 1 : 0,
      classification: "C1" as const,
    }),
  ),
];

const zonesWithRules: WaterZone[] = zones.map((z) =>
  z.zone_id === "WZ-PS23-LAURELSPUR" ? { ...z, pressure_psi_x10: 79 } : z,
);

export const handlers = [
  http.get("/api/water/zones", () => HttpResponse.json(zoneRulesOn() ? zonesWithRules : zones)),
  http.get("/api/water/advisories", () => HttpResponse.json(register())),
  http.get("/api/water/rules", () => HttpResponse.json(rules)),
  http.get("/api/anomalies", async () => {
    await delay(30);
    return HttpResponse.json(replayAnomalies.filter((a) => Date.parse(a.detected_at) <= Date.parse(asOf())));
  }),
  http.get("/api/models/anomaly_a7_a8/evaluation", () => HttpResponse.json(anomalyReport)),
  http.get("/api/policies", () =>
    HttpResponse.json(Object.entries(POLICIES).map(([key, p]) => ({ key, ...p }))),
  ),
];

type Ranged = { p10: string; p50: string; p90: string };
const at = (day: string, hm: string) => `2024-09-${day}T${hm}:00Z`;
const plus = (iso: string, min: number) =>
  new Date(Date.parse(iso) + min * 60_000).toISOString().replace(".000Z", "Z");

const BASIS = {
  kind: "model_estimate" as const,
  basis_id: "water_twin.zone_drain_critical_node",
  basis_version: "1.2-synthetic",
  citation: "SC R.61-58.7.E(7) 25 psi normal operation",
};
const modelBasis = (id: string) => ({
  kind: "model_estimate" as const,
  basis_id: id,
  basis_version: "1.2-synthetic",
  citation: null,
});
const LEAD_BASIS = (id: string) => ({
  kind: "model_estimate" as const,
  basis_id: id,
  basis_version: "1.2-synthetic",
  citation: null,
});

function clock(
  range: Ranged,
  lead: number,
  ifLate: string,
  basis: typeof BASIS | ReturnType<typeof modelBasis> = BASIS,
  leadBasis = LEAD_BASIS("water_twin.lead_times"),
) {
  return {
    decide_by_utc: range.p50,
    decide_by_p10_utc: range.p10,
    decide_by_p90_utc: range.p90,
    consequence_utc: plus(range.p50, lead),
    consequence_p10_utc: plus(range.p10, lead),
    consequence_p90_utc: plus(range.p90, lead),
    consequence_basis: basis,
    action_lead_time_min: lead,
    lead_time_basis: leadBasis,
    clock_kind: "model_estimate" as const,
    if_late: ifLate,
  };
}

/** PS-17 chain at advisory N+1 from `sgw clocks compute -i ps17_clock_members.json -a N+1` (decide-by P10, P50, P90, effective). */
const CHAIN = {
  fuel: {
    range: { p10: at("28", "14:05"), p50: at("28", "14:59"), p90: at("28", "16:06") },
    effective: at("27", "01:59"),
    lead: 90,
    basis: modelBasis("water_twin.portable_generator_fuel"),
  },
  power: {
    range: { p10: at("27", "02:43"), p50: at("27", "03:59"), p90: at("27", "05:44") },
    effective: at("27", "03:29"),
    lead: 150,
    basis: BASIS,
  },
  pressure: {
    range: { p10: at("27", "04:43"), p50: at("27", "05:59"), p90: at("27", "07:44") },
    effective: at("27", "05:59"),
    lead: 30,
    basis: BASIS,
  },
  hospital: {
    range: { p10: at("27", "09:13"), p50: at("27", "10:29"), p90: at("27", "12:14") },
    effective: at("27", "10:29"),
    lead: 120,
    basis: modelBasis("water_twin.hospital_storage"),
  },
};

type CardPatch = Omit<Partial<ProposalCard>, "case"> & { case?: Partial<ProposalCard["case"]> };

function waterCard(base: ProposalCard, patch: CardPatch): ProposalCard {
  return { ...base, ...patch, case: { ...base.case, ...patch.case } };
}

/** What each case of the PS-17 chain acts on, by the reference positions: the depot, the station, the zone, the hospital. */
const CHAIN_TARGETS: Record<string, string[]> = {
  "DC-D3-PS17-FUEL": ["DEP-AIK-GRANITEVILLE", "PS-17"],
  "DC-D3-PS17-PRESSURE": ["PS-17", "WZ-PS17-CEDARFALL"],
  "DC-D3-HSP-TALLOWBRANCH-WATER": ["HSP-AIK-TALLOWBRANCH"],
};

/** Puts the PS-17 chain at its N+1 values on the shared queue: patches the generator card, adds fuel, pressure and hospital. */
export function decorateCards(cards: ProposalCard[]): ProposalCard[] {
  return withZoneRules(decoratePs17Chain(cards));
}

function decoratePs17Chain(cards: ProposalCard[]): ProposalCard[] {
  const power = cards.find((c) => c.decision_case_id === "DC-D3-PS17-POWER");
  if (!power || cards.some((c) => c.decision_case_id === "DC-D3-PS17-FUEL")) return cards;
  const sibling = (
    id: string,
    caseId: string,
    title: string,
    key: keyof typeof CHAIN,
    ifLate: string,
    path: boolean,
    prereq: string[],
  ): ProposalCard =>
    waterCard(power, {
      proposal_id: id,
      decision_case_id: caseId,
      action_type: "work_order_draft",
      title,
      tier: "T2",
      decide_by_utc: CHAIN[key].range.p50,
      effective_decide_by_utc: CHAIN[key].effective,
      on_critical_path: path,
      functions_required: ["water_operations"],
      approvals: [],
      rationale: ifLate,
      case: {
        decision_case_id: caseId,
        title,
        on_critical_path: path,
        prerequisite_ids: prereq,
        effective_decide_by_utc: CHAIN[key].effective,
        no_regret_verdict: "act_now",
        no_regret_share_ppm: 925_000,
        clock: clock(CHAIN[key].range, CHAIN[key].lead, ifLate, CHAIN[key].basis),
      },
    });
  const patched = cards.map((c) =>
    c === power
      ? waterCard(power, {
          decide_by_utc: CHAIN.power.range.p50,
          effective_decide_by_utc: CHAIN.power.effective,
          case: {
            prerequisite_ids: ["DC-D3-PS17-FUEL", "DC-D2-CREWS-AIK"],
            effective_decide_by_utc: CHAIN.power.effective,
            clock: clock(
              CHAIN.power.range,
              CHAIN.power.lead,
              "Pressure at the hospital connection falls below the state floor.",
            ),
          },
        })
      : c,
  );
  return [
    ...patched,
    sibling(
      "PRP-PS17-FUEL",
      "DC-D3-PS17-FUEL",
      "Send the fuel truck to the PS-17 generator",
      "fuel",
      "The portable generator at PS-17 runs out of fuel.",
      true,
      [],
    ),
    sibling(
      "PRP-PS17-PRESSURE",
      "DC-D3-PS17-PRESSURE",
      "Hold pressure in the Cedarfall zone after power returns",
      "pressure",
      "Cedarfall pressure stays below the floor after power returns.",
      true,
      ["DC-D3-PS17-POWER"],
    ),
    sibling(
      "PRP-HSP-WATER",
      "DC-D3-HSP-TALLOWBRANCH-WATER",
      "Supply water to Tallow Branch hospital",
      "hospital",
      "Hospital water storage runs out.",
      false,
      ["DC-D3-PS17-PRESSURE"],
    ),
  ].map((c) =>
    CHAIN_TARGETS[c.decision_case_id]
      ? { ...c, target_ids: CHAIN_TARGETS[c.decision_case_id] as string[] }
      : c,
  );
}

type RuleSeed = {
  id: string;
  caseId: string;
  action: ProposalCard["action_type"];
  title: string;
  state: ProposalCard["state"];
  tier: ProposalCard["tier"];
  functions: ProposalCard["functions_required"];
  targets: string[];
  decideBy: string;
  params: Record<string, unknown>;
  domain?: "water" | "electric";
};

const RULE_SEEDS: RuleSeed[] = [
  {
    id: "PRP-ZR-LAURELSPUR-BWA",
    caseId: "DC-D3-PS23-LAURELSPUR-BWA",
    action: "boil_water_notice",
    title: "Issue a boil water advisory for the Laurelspur zone",
    state: "proposed",
    tier: "T3",
    functions: ["water_operations", "compliance"],
    targets: ["WZ-PS23-LAURELSPUR"],
    decideBy: at("27", "13:17"),
    params: { zone_id: "WZ-PS23-LAURELSPUR", clause: "SC-A1", floor_clause: "SC-P1" },
  },
  {
    id: "PRP-ZR-DEERWATER-BWA",
    caseId: "DC-D3-PS52-DEERWATER-BWA",
    action: "boil_water_notice",
    title: "Issue a boil water advisory for the Deerwater zone",
    state: "approved",
    tier: "T3",
    functions: ["water_operations", "compliance"],
    targets: ["WZ-PS52-DEERWATER"],
    decideBy: at("28", "19:45"),
    params: { zone_id: "WZ-PS52-DEERWATER", clause: "SC-A1", floor_clause: "SC-P1" },
  },
  {
    id: "PRP-ZR-COPPERLEAF-LIFT",
    caseId: "DC-D3-PS38-COPPERLEAF-BWA-LIFT",
    action: "lift_boil_water_notice",
    title: "Lift the boil water advisory for the Copperleaf zone",
    state: "proposed",
    tier: "T3",
    functions: ["water_operations", "compliance"],
    targets: ["WZ-PS38-COPPERLEAF"],
    decideBy: at("30", "21:41"),
    params: {
      zone_id: "WZ-PS38-COPPERLEAF",
      clean_sets: 2,
      clauses_met: ["SC-L1"],
      pending_clause: "SC-L4",
    },
  },
  {
    id: "PRP-ZR-CEDARFALL-LIFT",
    caseId: "DC-D3-PS17-CEDARFALL-BWA-LIFT",
    action: "lift_boil_water_notice",
    title: "Lift the boil water advisory for the Cedarfall zone",
    state: "approved",
    tier: "T3",
    functions: ["water_operations", "compliance"],
    targets: ["WZ-PS17-CEDARFALL"],
    decideBy: at("30", "09:21"),
    params: { zone_id: "WZ-PS17-CEDARFALL", clean_sets: 2, clauses_met: ["SC-L3", "SC-L1"] },
  },
  {
    id: "PRP-ZR-HSP-TANKER",
    caseId: "DC-D3-HSP-TALLOWBRANCH-TANKER",
    action: "field_resource_order",
    title: "Send a water tanker to Tallowbranch hospital",
    state: "proposed",
    tier: "T2",
    functions: ["logistics"],
    targets: ["WTK-CORDGRASS-2"],
    decideBy: at("27", "10:29"),
    params: {
      resource_kind: "potable_water_tanker",
      zone_id: "WZ-PS17-CEDARFALL",
      destination_id: "HSP-AIK-TALLOWBRANCH",
    },
  },
  {
    id: "PRP-ZR-RESTORE-ORDER",
    caseId: "DC-D3-AIK-RESTORE-ORDER",
    action: "cross_domain_priority",
    title: "Set the restoration order of FDR-AIK-2219 and FDR-AIK-2207",
    state: "proposed",
    tier: "T3",
    functions: ["command", "water_operations"],
    targets: ["FDR-AIK-2207", "FDR-AIK-2219"],
    decideBy: at("27", "13:05"),
    params: { zone_id: "WZ-PS17-CEDARFALL", station_id: "PS-17" },
    domain: "electric",
  },
];

function withZoneRules(cards: ProposalCard[]): ProposalCard[] {
  const base = cards.find((c) => c.decision_case_id === "DC-D3-PS17-POWER");
  if (!zoneRulesOn() || !base || cards.some((c) => c.proposal_id === RULE_SEEDS[0]?.id)) return cards;
  const added = RULE_SEEDS.map((seed) =>
    waterCard(base, {
      proposal_id: seed.id,
      decision_case_id: seed.caseId,
      action_type: seed.action,
      title: seed.title,
      state: seed.state,
      tier: seed.tier,
      decide_by_utc: seed.decideBy,
      effective_decide_by_utc: seed.decideBy,
      on_critical_path: false,
      functions_required: seed.functions,
      approvals: [],
      target_ids: seed.targets,
      params: seed.params,
      case: {
        decision_case_id: seed.caseId,
        title: seed.title,
        domain: seed.domain ?? "water",
        on_critical_path: false,
        prerequisite_ids: [],
        effective_decide_by_utc: seed.decideBy,
        no_regret_verdict: "n/a",
        clock: clock(
          { p10: seed.decideBy, p50: seed.decideBy, p90: seed.decideBy },
          60,
          "Customers keep waiting for the next step.",
        ),
      },
    }),
  );
  return [...cards, ...added];
}

const SAMPLES_NEEDED = 2;
const baseRows = advisories.advisories as BwaAdvisory[];

const staged = (row: BwaAdvisory, extra: Partial<BwaAdvisory>): BwaAdvisory => ({
  stage: row.status === "due" || row.status === "proposed" ? "due" : null,
  clean_samples: 0,
  samples_needed: SAMPLES_NEEDED,
  lift_proposal_id: null,
  lift_decision_case_id: null,
  ...row,
  ...extra,
});

const pressureLoss = (zoneId: string, station: string, dueUtc: string, extra: Partial<BwaAdvisory>) =>
  staged(
    {
      ...(baseRows[0] as BwaAdvisory),
      advisory_id: `BWA-${zoneId}-PRESSURELOSS`,
      zone_id: zoneId,
      station_id: station,
      kind: "pressure_loss",
      clause_ids: ["SC-A1", "SC-P1"],
      assessments: [],
      sensitivity: [],
      due_utc: dueUtc,
      proposal_id: null,
      decision_case_id: null,
    },
    extra,
  );

/** The register as `GET /api/water/advisories` reports it; with the zone rules on, the four zones at four stages of the proposals above. */
function register(): { advisories: BwaAdvisory[] } {
  if (!zoneRulesOn()) return { advisories: baseRows.map((r) => staged(r, {})) };
  const cedarfall = baseRows.map((r) =>
    staged(r, {
      status: "lifted",
      stage: "lifted",
      clean_samples: 2,
      lift_proposal_id: "PRP-ZR-CEDARFALL-LIFT",
      lift_decision_case_id: "DC-D3-PS17-CEDARFALL-BWA-LIFT",
    }),
  );
  return {
    advisories: [
      ...cedarfall,
      pressureLoss("WZ-PS23-LAURELSPUR", "PS-23", "2024-09-27T10:17:00Z", {
        status: "proposed",
        stage: "due",
        proposal_id: "PRP-ZR-LAURELSPUR-BWA",
        decision_case_id: "DC-D3-PS23-LAURELSPUR-BWA",
      }),
      pressureLoss("WZ-PS38-COPPERLEAF", "PS-38", "2024-09-28T05:38:00Z", {
        status: "issued",
        stage: "lift_decision",
        clean_samples: 2,
        lift_proposal_id: "PRP-ZR-COPPERLEAF-LIFT",
        lift_decision_case_id: "DC-D3-PS38-COPPERLEAF-BWA-LIFT",
      }),
      pressureLoss("WZ-PS52-DEERWATER", "PS-52", "2024-09-28T16:45:00Z", {
        status: "issued",
        stage: "samples",
        clean_samples: 1,
        proposal_id: "PRP-ZR-DEERWATER-BWA",
        decision_case_id: "DC-D3-PS52-DEERWATER-BWA",
      }),
    ],
  };
}
