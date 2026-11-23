import type { ApprovalFunction } from "@/contracts/vocab.gen";
import { SEED_USERS } from "./personas.gen";

export interface Persona {
  user_id: string;
  title: string;
  function: ApprovalFunction;
}

/** The K18 seeded identities, generated from data/seed/users.yaml. Identifiers and names only; passwords never live here. */
export const PERSONAS: readonly Persona[] = SEED_USERS.map((u) => ({
  user_id: u.user_id,
  title: u.display_name,
  function: u.function,
}));

export const FUNCTION_LABEL: Record<ApprovalFunction, string> = {
  command: "Command",
  operations: "Operations",
  planning: "Planning",
  logistics: "Logistics",
  water_operations: "Water operations",
  compliance: "Compliance",
  executive: "Executive",
  audit: "Audit",
  platform: "Platform",
  data: "Data",
  communications: "Communications",
};
