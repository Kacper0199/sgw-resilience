import { NUMBERS } from "@/contracts/numbers.gen";
import type { AnswerPath, AnswerReason, Reference } from "../types";

export interface MockTool {
  tool: string;
  args: Record<string, unknown>;
}

export interface MockScript {
  match: RegExp;
  tools: MockTool[];
  path: AnswerPath;
  reason?: AnswerReason;
  text: string;
  citations: string[];
  evidenceIds: string[];
  references: Reference[];
  tainted: boolean;
  /** The R33 additions, in the wire shape: links, photos, suggestions, refusal. */
  extras?: Record<string, unknown>;
}

const etFromDay27 = (minutes: number): string => {
  const et = minutes - 4 * 60;
  const day = et < 0 ? 26 : 27;
  const m = (et + 24 * 60) % (24 * 60);
  return `Sep ${day}, ${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")} ET`;
};
const decideN1 = etFromDay27(NUMBERS.demo_ps17_decide_by_n1_min.value);

const ETR_SOURCE =
  '[1] DOM 14.206 Rev K, 6.0 PROCEDURE; 7.0 RECORDS; 8.0 REFERENCES; ATTACHMENT A - Release Decision Table, pp. 2-4: "6.4.2 Revise a published ETR when the P50 moves by more than 12 h."';
const ETR_SOURCE_2 =
  '[2] DOM 14.206 Rev K, 6.0 PROCEDURE; 7.0 RECORDS; 8.0 REFERENCES; ATTACHMENT A - Release Decision Table, pp. 2-4: "6.4.4 Revised ETRs need the same approvals as in 6.2.4."';

const decision = (id: string, label: string): Reference => ({ kind: "decision", id, label });
const asset = (id: string, label: string): Reference => ({ kind: "asset", id, label });
const LATEST: Reference = {
  kind: "advisory",
  id: "2024-09-26T15:00:00Z",
  label: "Advisory of Sep 26, 11:00 ET",
};
const POWER = decision("DC-D3-PS17-POWER", "Hook up the portable generator at PS-17");
const FUEL = decision("DC-D3-PS17-FUEL", "Dispatch the fuel truck to PS-17");
const PRESSURE = decision("DC-D3-PS17-PRESSURE", "Hold Cedarfall zone pressure above the state floor");
const HOSPITAL = decision("DC-D3-HSP-TALLOWBRANCH-WATER", "Secure water supply to Tallowbranch hospital");
const PS17 = asset("PS-17", "Cedarfall pump station");

const photo = (n: string, caption: string) => ({
  photo_id: `ladi-v2-test-${n}`,
  thumb_url: `/api/damage/thumbs/ladi-v2-test-${n}`,
  href: `/crews?photo=ladi-v2-test-${n}`,
  caption,
  provenance: "Civil Air Patrol aerial photos (LADI v2), CC BY 4.0",
});

const SUGGESTIONS = [
  "What must we decide before the next advisory?",
  "Which pump stations need power?",
  "Show the damage photos",
];

/** The recorded answers of the starters at the latest advisory, as the API returns them (text, tools, references). */
export const SCRIPTS: MockScript[] = [
  {
    match: /^(show|pokaż).*(photos?|zdj)/i,
    tools: [{ tool: "get_damage_photos", args: { county: "45003" } }],
    path: "llm",
    text: "Here are the four highest-scoring photos of flooding. Photo ladi-v2-test-0016 shows a flooded road near Aiken. A person reviews every photo before it changes a crew plan.",
    citations: [],
    evidenceIds: [],
    references: [],
    tainted: false,
    extras: {
      photos: [
        photo("0016", "Flooded road near Aiken"),
        photo("0049", "Flooded houses, Savannah River"),
        photo("0021", "Debris on a county road"),
        photo("0042", "Standing water at a substation"),
      ],
      links: [{ kind: "page", label: "All damage photos", href: "/crews?tab=photos", page: "crews" }],
      suggestions: ["Which crews can reach these?", "What does the damage model see?"],
    },
  },
  {
    match: /where.*(water|information)|how do i find/i,
    tools: [],
    path: "guide",
    text: "Water information is in the Water page: pump stations, pressure by zone and boil-water notices. The Cedarfall zone is the one to watch while PS-17 runs on a generator.",
    citations: [],
    evidenceIds: [],
    references: [],
    tainted: false,
    extras: {
      links: [
        { kind: "page", label: "Water page", href: "/water", page: "water" },
        { kind: "zone", label: "Cedarfall zone", href: "/water?zone=WZ-PS17-CEDARFALL", page: "water" },
        { kind: "page", label: "Map", href: "/map", page: "map" },
      ],
      suggestions: SUGGESTIONS,
    },
  },
  {
    match: /ps-?71\b|did you mean/i,
    tools: [],
    path: "guide",
    text: "Did you mean the pump station PS-17 or PS-7?",
    citations: [],
    evidenceIds: [],
    references: [],
    tainted: false,
    extras: { did_you_mean: ["What is the status of PS-17?", "What is the status of PS-7?"] },
  },
  {
    match: /tide table|tides/i,
    tools: [],
    path: "guide",
    text: "Tide tables are not on this platform. The Forecast page shows the storm surge expected for each county.",
    citations: [],
    evidenceIds: [],
    references: [],
    tainted: false,
    extras: {
      links: [{ kind: "forecast", label: "Forecast page", href: "/forecast", page: "forecast" }],
      suggestions: ["How high will the surge be in Aiken?"],
    },
  },
  {
    match: /weather in|recipe|joke/i,
    tools: [],
    path: "guide",
    text: "That is outside what I can help with here. I answer questions about the storm response: decisions and their deadlines, power and water outages, crews, forecasts, photos and where things are in the platform.",
    citations: [],
    evidenceIds: [],
    references: [],
    tainted: false,
    extras: { refusal: "unrelated", suggestions: SUGGESTIONS },
  },
  {
    match: /latest advisory.*ps-17|ps-17.*deadline/i,
    tools: [
      { tool: "get_decision_case", args: { decision_case_id: "DC-D3-PS17-POWER" } },
      { tool: "get_decision_case", args: { decision_case_id: "DC-D3-PS17-FUEL" } },
      { tool: "get_decision_case", args: { decision_case_id: "DC-D3-PS17-PRESSURE" } },
    ],
    path: "llm",
    text: `The latest advisory puts the PS-17 generator hookup, DC-D3-PS17-POWER, at "decide before the next advisory". Its effective decide-by is ${decideN1}, because the fuel dispatch, DC-D3-PS17-FUEL, and the crew pre-positioning must happen first.`,
    citations: [],
    evidenceIds: ["E1", "E2", "E3"],
    references: [LATEST, PS17, POWER, FUEL],
    tainted: false,
  },
  {
    match: /tallowbranch|hospital/i,
    tools: [
      { tool: "get_decision_case", args: { decision_case_id: "DC-D3-HSP-TALLOWBRANCH-WATER" } },
      { tool: "get_decision_case", args: { decision_case_id: "DC-D3-PS17-PRESSURE" } },
      { tool: "get_decision_case", args: { decision_case_id: "DC-D3-PS17-POWER" } },
    ],
    path: "llm",
    text: "Securing the hospital's water, DC-D3-HSP-TALLOWBRANCH-WATER, needs DC-D3-PS17-PRESSURE first. That in turn needs DC-D3-PS17-POWER, the PS-17 generator hookup, which is to be decided before the next advisory.",
    citations: [],
    evidenceIds: ["E1", "E2", "E3"],
    references: [HOSPITAL, PRESSURE, POWER, PS17],
    tainted: false,
  },
  {
    match: /revise.*etr|etr.*revise/i,
    tools: [{ tool: "search_procedures", args: { query: "revise a published global ETR when P50 moves" } }],
    path: "llm",
    text: `Revise a published ETR when the P50 moves by more than the margin the procedure sets.[1] A smaller move is logged but not released. Revised ETRs need the same approvals as the original release.[2] This is in DOM 14.206.\n\nSources:\n${ETR_SOURCE}\n${ETR_SOURCE_2}`,
    citations: ["DOM 14.206 Rev K"],
    evidenceIds: [],
    references: [{ kind: "clause", id: "DOM 14.206", label: "6.0 PROCEDURE; 7.0 RECORDS; 8.0 REFERENCES" }],
    tainted: false,
  },
  {
    match: /pump stations?.*generator|generator.*pump stations?/i,
    tools: [{ tool: "get_water_status", args: {} }],
    path: "llm",
    text: "PS-38 and PS-52 have their own generators: GEN-PS38-COPPERLEAF at PS-38 and GEN-PS52-DEERWATER at PS-52. PS-17 and PS-23 have no onsite generator.",
    citations: [],
    evidenceIds: ["E1", "E2", "E3", "E4"],
    references: [
      asset("PS-38", "Copperleaf pump station"),
      asset("PS-52", "Deerwater pump station"),
      asset("GEN-PS38-COPPERLEAF", "Onsite generator at PS-38"),
      asset("GEN-PS52-DEERWATER", "Onsite generator at PS-52"),
      PS17,
      asset("PS-23", "Laurelspur pump station"),
    ],
    tainted: false,
  },
  {
    match: /surge/i,
    tools: [
      { tool: "list_outage_surges", args: { county: "45003" } },
      { tool: "get_damage_photos", args: { county: "45003" } },
    ],
    path: "llm",
    text: "Aiken surge, Sep 27 00:00 ET is the largest rise since the last advisory. Damage photo LADI-0042 shows a flooded road near gauge 02197000. Crew CRW-AIK-04 at STG-AIK-SANDHILL-YARD can reach it. Cedarfall zone WZ-PS17-CEDARFALL stays above its floor, and readiness check DC-RDY-GEN-PS52-LOADTEST is open.",
    citations: [],
    evidenceIds: [],
    references: [
      { kind: "surge", id: "45003@2024-09-27T04:00:00Z", label: "Aiken surge, Sep 27 00:00 ET" },
      { kind: "photo", id: "LADI-0042", label: "Flooded road near Aiken" },
      { kind: "gauge", id: "02197000", label: "Savannah River gauge" },
      { kind: "crew", id: "CRW-AIK-04", label: "Aiken line crew 4" },
      { kind: "yard", id: "STG-AIK-SANDHILL-YARD", label: "Sandhill staging yard" },
      { kind: "zone", id: "WZ-PS17-CEDARFALL", label: "Cedarfall zone" },
      { kind: "check", id: "DC-RDY-GEN-PS52-LOADTEST", label: "Load test of the PS-52 generator" },
    ],
    tainted: false,
  },
  {
    match: /new tickets/i,
    tools: [{ tool: "search_procedures", args: { query: "new tickets", top_k: 5 } }],
    path: "llm",
    text: `The tools have no ticket queue, so I cannot confirm whether any new tickets exist. The nearest item is a field record, which is unverified and is not procedure. It is delivery ticket MAL-TKT-ALT-240927-118, a scheduled diesel delivery to GEN-PS38-COPPERLEAF.[1] Station Operators record each delivery on F-WDS-207 with the ticket number.[2]\n\nSources:\n[1] [field record, unverified] MAL-TKT-ALT-240927-118, Control box; Order; Dispatch Notes; Delivery Record (completed by driver at site), pp. 1-2: "Delivery of diesel to GEN-PS38-COPPERLEAF scheduled, route via Copperleaf Road."\n[2] MAL-CTR-0447 Rev B, 5.0 DECLARED-EVENT PROVISIONS; 6.0 ORDERING; 7.0 DELIVERY TICKETS AND RECORDS, pp. 2-3: "7.3 Station Operators record the delivery on F-WDS-207 with the ticket number."`,
    citations: ["MAL-TKT-ALT-240927-118", "MAL-CTR-0447 Rev B"],
    evidenceIds: [],
    references: [asset("GEN-PS38-COPPERLEAF", "Onsite generator at PS-38")],
    tainted: true,
  },
  {
    match: /paper tickets?/i,
    tools: [
      { tool: "get_decision_case", args: { decision_case_id: "DC-D3-PS17-POWER" } },
      { tool: "search_procedures", args: { query: "paper tickets degraded mode" } },
    ],
    path: "m2",
    reason: "checks_failed",
    text: `Evidence gathered for this question (no model text):\n[E1] DC-D3-PS17-POWER Hook up the portable generator at PS-17: decide by ${decideN1}; before next advisory\n[1] DOM 14.190 Rev B, 4.0 DEFINITIONS; 5.0 DEGRADED MODES; 6.0 PROCEDURE, pp. 2-3: "Paper ticket: the printed trouble ticket on the storm room pad, numbered in sequence per district."`,
    citations: ["DOM 14.190 Rev B"],
    evidenceIds: ["E1"],
    references: [POWER, PS17],
    tainted: false,
  },
];

/** The never-break answer: the assistant could not write, so the platform's data is shown with its links. */
export const FALLBACK_SCRIPT: MockScript = {
  match: /sandhill|crew yards?/i,
  tools: [
    { tool: "get_decision_case", args: { decision_case_id: "DC-D2-CREWS-AIK" } },
    { tool: "search_procedures", args: { query: "sandhill yard crews" } },
  ],
  path: "m2",
  reason: "llm_unavailable",
  text: "Evidence gathered for this question (no model text):\n[E1] DC-D2-CREWS-AIK Pre-position crews at Sandhill and Millpond yards: decide by Sep 26, 20:15 ET",
  citations: [],
  evidenceIds: ["E1"],
  references: [
    decision("DC-D2-CREWS-AIK", "Pre-position crews at Sandhill and Millpond yards"),
    { kind: "yard", id: "STG-AIK-SANDHILL-YARD", label: "Sandhill staging yard" },
  ],
  tainted: false,
};

export const NOT_FOUND_SCRIPT = (question: string): MockScript => ({
  match: /^$/,
  tools: [{ tool: "search_procedures", args: { query: question.slice(0, 60).toLowerCase() } }],
  path: "not_in_documents",
  text: "This is not in the documents.",
  citations: [],
  evidenceIds: [],
  references: [],
  tainted: false,
});

export const pickScript = (question: string): MockScript =>
  [...SCRIPTS, FALLBACK_SCRIPT].find((s) => s.match.test(question)) ?? NOT_FOUND_SCRIPT(question);
