import type { GlossaryEntry } from "./glossary";

export const AFTERACTION_ADMIN_GLOSSARY = {
  after_action: {
    term: "After-action review",
    text: "What was decided, by whom and when, from the audit log. Nothing here changes a decision.",
  },
  verify_chain: {
    term: "Check audit log",
    text: "Rechecks every entry from the first one and shows the first entry that doesn't match, if any.",
  },
  notary: {
    term: "Independent check",
    text: "A separate key confirms the latest audit-log entry. Confirmed means it matches a saved checkpoint; not confirmed means it couldn't be checked.",
  },
  first_bad_seq: {
    term: "First bad entry",
    text: "The earliest audit-log entry that no longer matches. Nothing from there on can be trusted.",
  },
  tamper_demo: {
    term: "Tamper test",
    text: "Changes one entry on a copy of the audit log and runs the check. The real log is never touched.",
  },
  clock_outcome: {
    term: "Met or missed",
    text: "Met: approved (by two signatures or alone in an emergency) by the deadline. Missed: approved later, or never.",
  },
  cosign: {
    term: "Co-sign",
    text: "After an emergency approval, a second team must co-sign within 24 hours. Late or missing co-signs are flagged here.",
  },
  scorecard: {
    term: "ETR accuracy",
    text: "How far each ETR was from what happened. The actual is simulated, so this is practice, not field proof.",
  },
  analog_baseline: {
    term: "Past-storm average",
    text: "The typical restoration time in past storms of the same kind. SGW's estimate should beat it.",
  },
  sc_report: {
    term: "SC 103-314 draft",
    text: "A draft of the interruption report South Carolina requires after a long outage. Nothing is filed from here; the filer adds notice times.",
  },
  policy_param: {
    term: "Policy value",
    text: "A number SGW chose by policy, not a legal limit. Read-only; changing one needs a decision and signatures.",
  },
  page_admin: {
    term: "Admin",
    text: "Who can sign what, the policy values, integrations, the audit log and AI settings. Everything here is read-only.",
  },
  approval_rights: {
    term: "Approval rights",
    text: "What each person can sign, by action and tier. Emergency approval rules are on each decision's Signatures tab.",
  },
  data_class_ceiling: {
    term: "Data allowed",
    text: "The most sensitive data this AI step may see. C1 is operational data with no personal details.",
  },
  effort: {
    term: "Effort",
    text: "How much the AI step may reason before answering. Higher is slower and costs more.",
  },
  allowed_tools: {
    term: "Allowed lookups",
    text: "The read-only lookups this AI step may use. Text-only steps have none. No step can sign or send anything.",
  },
  api_scope: {
    term: "Scope",
    text: "What a token can read. No token can sign or change a decision.",
  },
  webhook: {
    term: "Webhook",
    text: "A web address SGW notifies when a decision changes. Failed sends retry, then stop and are listed here.",
  },
  system_metrics: {
    term: "System metrics",
    text: "Requests and response times, counted by the platform itself. Grafana adds charts when monitoring runs.",
  },
} as const satisfies Record<string, GlossaryEntry>;
