/** Demo mode only: the sign-in chooser lives in this module, which the page loads on demand once GET /api/auth/config says demo. The password comes from that response, and only when it is true. */

export interface DemoPerson {
  user_id: string;
  initials: string;
  line: string;
}

export const DEMO_PEOPLE: readonly DemoPerson[] = [
  { user_id: "ic_01", initials: "IC", line: "Leads the response and signs the final call." },
  {
    user_id: "ops_dm_01",
    initials: "DM",
    line: "Runs the grid shift and approves switching and crew moves.",
  },
  {
    user_id: "wtr_lead_01",
    initials: "WL",
    line: "Leads the water response: pump stations, pressure and advisories.",
  },
  {
    user_id: "wtr_comp_01",
    initials: "WC",
    line: "Checks water actions against the rules and regulator notices.",
  },
  { user_id: "log_01", initials: "LC", line: "Plans crews, fuel and equipment." },
  { user_id: "plan_etr_01", initials: "ET", line: "Estimates when power will be back." },
  { user_id: "exec_01", initials: "EX", line: "Reads the briefing. Read-only." },
];

export const DEMO_OTHERS: readonly DemoPerson[] = [
  {
    user_id: "ops_dm_02",
    initials: "DR",
    line: "Takes over the grid shift from the first Duty Manager.",
  },
  { user_id: "audit_01", initials: "AU", line: "Reviews the audit log. Read-only." },
  { user_id: "admin_01", initials: "PA", line: "Manages users and settings." },
  { user_id: "ml_01", initials: "MO", line: "Owns data feeds and forecast models." },
];
