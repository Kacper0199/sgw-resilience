/** Plain names for graph nodes; a node nobody named reads as its words, never its id. */
export const NODE_LABEL: Record<string, string> = {
  load_context: "Read the question",
  route_intent: "Work out what was asked",
  investigate: "Look things up",
  plan: "Split the question",
  worker: "Analysts look things up",
  gather: "Collect the findings",
  synthesise: "Write the answer",
  link: "Link what it names",
  respond: "Finish the answer",
  audit: "Log the question",
  input_guard: "Screen the question for misuse",
  sitrep_evidence: "Collect the numbers",
  sitrep: "Draft the report",
  verify: "Check every number",
  sitrep_draft: "Save the draft",
};

export interface PlanStep {
  label: string;
  nodes: string[];
  /** The step is done when any lookup ran, even if its graph node never reported. */
  looksUp?: boolean;
}

/** The fixed shape of each graph, as the checklist a person reads under "How I got this". */
export const PLANS: Record<string, PlanStep[]> = {
  copilot: [
    { label: "Work out what was asked", nodes: ["load_context", "route_intent"] },
    { label: "Look up platform data and procedures", nodes: ["investigate"], looksUp: true },
    { label: "Check the answer against its sources", nodes: ["link", "respond", "audit"] },
  ],
  sitrep: [
    {
      label: "Collect the numbers from the platform",
      nodes: ["load_context", "input_guard", "sitrep_evidence"],
    },
    { label: "Draft the report", nodes: ["sitrep"] },
    { label: "Check every number against its source", nodes: ["verify"] },
    { label: "Save the draft for a person to confirm", nodes: ["sitrep_draft", "audit"] },
  ],
};

export const TOOL_LABEL: Record<string, string> = {
  get_decision_case: "Decision deadline",
  get_water_status: "Water status",
  get_forecast: "Forecast",
  search_procedures: "Procedure search",
  get_risk: "Outage risk",
  get_outages: "Outages",
  get_crews: "Crews",
  list_anomalies: "Sensor checks",
  get_feed_health: "Data feeds",
  run_what_if: "What-if",
  list_decisions: "Decision queue",
  get_readiness: "Readiness",
  get_etr: "Restoration times",
  list_outage_surges: "Outage surges",
  get_damage_photos: "Damage photos",
};

const sentence = (id: string): string => {
  const words = id.replace(/[_:-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
};

/** "worker:water" reads as "Water analyst looks things up". */
export function nodeLabel(node: string): string {
  const [kind, name] = node.split(":");
  if (kind === "worker" && name) return `${sentence(name)} analyst looks things up`;
  return NODE_LABEL[node] ?? NODE_LABEL[kind ?? ""] ?? sentence(node);
}

/** What a lookup did, in plain words: "Read the decision", "Checked water status". */
export const TOOL_VERB: Record<string, string> = {
  get_decision_case: "Read the decision",
  get_water_status: "Checked water status",
  get_forecast: "Read the forecast",
  search_procedures: "Searched procedures",
  get_risk: "Checked outage risk",
  get_outages: "Read outages",
  get_crews: "Read crews",
  list_anomalies: "Checked sensors",
  get_feed_health: "Checked data feeds",
  run_what_if: "Ran a what-if",
  list_decisions: "Read the decision queue",
  get_readiness: "Checked readiness",
  get_etr: "Read restoration times",
  list_outage_surges: "Checked outage surges",
  get_damage_photos: "Read damage photos",
  get_flood_risk: "Checked flood risk",
};

export const toolVerb = (tool: string): string => TOOL_VERB[tool] ?? sentence(tool);
