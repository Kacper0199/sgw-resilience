/** Plain names for the configured AI steps (`/api/admin/ai-config` node ids); an unnamed step reads as its words. */
export const AI_STEP_LABEL: Record<string, string> = {
  narrate: "Explain a decision card",
  draft_rationale: "Draft the reason for a decision",
  rag_chunk_header: "Label procedure passages",
  answer_sop: "Answer from procedures",
  extract_note: "Read field notes",
  route_intent: "Sort the question",
  ask_contextualise: "Read the question in the conversation",
  triage_intent: "Second look at off-topic questions",
  ask_guide: "Guide around the platform",
  investigate: "Look things up",
  etr_brief: "Write the restoration estimate brief",
  sitrep: "Draft the situation report",
  after_action_summary: "Summarise the after-action review",
  ask_plan: "Split the question",
  ask_worker_forecast: "Forecast analyst",
  ask_worker_grid: "Grid analyst",
  ask_worker_water: "Water analyst",
  ask_worker_policy: "Policy analyst",
  ask_worker_data_quality: "Data quality analyst",
  ask_synth: "Write the answer",
};

export function aiStepName(node: string): string {
  const known = AI_STEP_LABEL[node];
  if (known) return known;
  const words = node.replace(/[_:-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
