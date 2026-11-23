import type { GlossaryEntry } from "./glossary";

export const HEALTH_GLOSSARY = {
  feed_freshness: {
    term: "Data age",
    text: "How old the latest data from each source is, against the maximum age SGW accepts. Older data is marked late, never shown as current.",
  },
  pipeline_run: {
    term: "Data load",
    text: "One pass that fetches, checks and stores data from a source. Rows held back failed a check and are left out.",
  },
  lineage: {
    term: "Data flow",
    text: "Where this data comes from and what uses it. If a source is late, everything that uses it is affected.",
  },
  dq_check: {
    term: "Data check",
    text: "An automatic test of the data, such as ranges, units and duplicates. A failed error check blocks the dataset; a warning only flags it.",
  },
  model_card: {
    term: "Model details",
    text: "What a model does, which version is in use, and how it scored on new storms against a simple baseline.",
  },
  ai_run: {
    term: "AI request",
    text: "One AI job, such as answering a question or drafting a report. Each is logged with its steps and cost.",
  },
  ai_trace: {
    term: "Steps",
    text: "The step-by-step record of a request: what was asked, what was looked up and what came back.",
  },
  degraded_mode: {
    term: "SGW mode",
    text: "How much of SGW is working. M0 is normal; each step up turns off more AI and live features, down to manual procedures only.",
  },
  kill_switch: {
    term: "Stop level",
    text: "Stops parts of SGW on purpose. K1 pauses signing, K2 stops the AI, K3 stops new data and decisions, and K4 turns SGW off.",
  },
  two_function_restore: {
    term: "Two-team resume",
    text: "Turning a stopped part back on needs two teams to sign, each with their password. Both signatures go in the audit log.",
  },
  readiness: {
    term: "Readiness",
    text: "Pre-season checks that crews, fuel, agreements, and equipment are ready. Each item not ready has an owner and a due date.",
  },
  readiness_status: {
    term: "Ready, not ready, no record",
    text: "Ready: proof is on file. Not ready: proof is missing or overdue. No record: nothing logged yet.",
  },
} as const satisfies Record<string, GlossaryEntry>;
