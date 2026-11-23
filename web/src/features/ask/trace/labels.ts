import { humanize } from "@/features/health/format";
import { modelName } from "@/lib/plain";
import type { CallMode } from "./model";

export const WORKER_LABEL: Record<string, string> = {
  forecast: "Forecast and hazard",
  grid: "Grid and crews",
  grid_crews: "Grid and crews",
  water: "Water",
  policy: "Policy and evidence",
  data_quality: "Data quality",
};

interface ToolFace {
  verb: string;
  tag?: string;
}

export const TOOL_FACE: Record<string, ToolFace> = {
  get_forecast: { verb: "Read forecast" },
  get_risk: { verb: "Read outage risk" },
  run_what_if: { verb: "Ran what-if" },
  get_flood_risk: { verb: "Read flood risk", tag: "Flood model" },
  get_outages: { verb: "Read outages" },
  list_outage_surges: { verb: "Looked for surges", tag: "Surge detector" },
  get_crews: { verb: "Read crews", tag: "Crew plan" },
  get_etr: { verb: "Read restoration times", tag: "ETR model" },
  get_damage_photos: { verb: "Read damage photos", tag: "LADI model" },
  get_water_status: { verb: "Read water status" },
  list_anomalies: { verb: "Checked sensors", tag: "A7 detector" },
  get_decision_case: { verb: "Read decision" },
  list_decisions: { verb: "Listed decisions" },
  search_procedures: { verb: "Searched procedures" },
  get_readiness: { verb: "Read readiness" },
  get_feed_health: { verb: "Read data feeds" },
};

export const toolFace = (tool: string): ToolFace => TOOL_FACE[tool] ?? { verb: humanize(tool) };

export const PHASE_LABEL: Record<string, string> = {
  question: "Question",
  plan: "Plan",
  workers: "Specialists",
  answer: "Answer",
  checks: "Checks",
  links: "Links",
};

export const CHECK_LABEL: Record<string, string> = {
  verify: "Ids and numbers match the data",
  finalise: "Sources cited",
};

export const workerLabel = (worker: string): string => WORKER_LABEL[worker] ?? humanize(worker);

export const shortModel = (id: string): string => modelName(id).replace(/^Claude /, "");

export const MODE_LABEL: Record<CallMode, string> = {
  replay: "Replay",
  live: "Live",
  cached: "Cached",
  other: "Other",
};
