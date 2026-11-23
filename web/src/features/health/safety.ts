import type { CapabilityKey, DegradedMode, KillLevel } from "./types";

export const KILL_ORDER: KillLevel[] = ["K0", "K1", "K2", "K3", "K4"];
export const MODE_ORDER: DegradedMode[] = ["M0", "M1", "M2", "M3", "M4"];

export const KILL_LEVELS: Record<KillLevel, { label: string; effect: string }> = {
  K0: { label: "Normal", effect: "Nothing is stopped." },
  K1: {
    label: "Signing paused",
    effect: "Pending signatures and unused approvals are canceled. Actions need new signatures once resumed.",
  },
  K2: {
    label: "AI stopped",
    effect: "Signing is paused, running AI requests stop and new ones are refused.",
  },
  K3: {
    label: "New data and decisions stopped",
    effect:
      "Signing and AI stay off. No new outside data, decisions or data loads. Existing plans stay readable.",
  },
  K4: { label: "Platform off", effect: "Everything is off. Use the manual control-room procedures." },
};

export const CAPABILITY_LABEL: Record<CapabilityKey, string> = {
  view_dashboards: "View pages",
  create_proposals: "Propose decisions",
  approve_and_execute: "Sign and carry out",
  agent_runs: "AI requests",
  llm_calls: "AI model use",
  free_form_plans: "AI choosing its own steps",
  ingest_external: "Receive outside data",
  pipeline_runs: "Load data",
  manual_workflow: "Manual procedures",
  crew_into_hazard_proposals: "Propose crews into hazard areas",
};
