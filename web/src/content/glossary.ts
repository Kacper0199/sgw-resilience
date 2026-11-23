import { AFTERACTION_ADMIN_GLOSSARY } from "./glossary.afteraction-admin";
import { ASK_BRIEF_GLOSSARY } from "./glossary.ask-brief";
import { ETR_GLOSSARY } from "./glossary.etr";
import { HEALTH_GLOSSARY } from "./glossary.health";
import { WATER_CREWS_GLOSSARY } from "./glossary.water-crews";

export interface GlossaryEntry {
  term: string;
  text: string;
}

export const GLOSSARY = {
  clock: {
    term: "Clock",
    text: "Time left before acting is too late. It counts down to the deadline.",
  },
  decide_by: {
    term: "Decide by",
    text: "Latest time to decide: when impact starts minus the lead time. The range covers 8 in 10 storm scenarios.",
  },
  tier: {
    term: "Approval",
    text: "How many people must sign. Tier 1: one person confirms. Tier 2: one approver signs. Tier 3: two approvers from two teams sign.",
  },
  tier_T0: { term: "View only", text: "Tier 0. Looking, asking and what-ifs. Logged; no signature needed." },
  tier_T1: {
    term: "1 person confirms",
    text: "Tier 1. One person confirms a draft. Also covers changes inside an already approved plan.",
  },
  tier_T2: { term: "1 team signs", text: "Tier 2. One approver from the named team must sign." },
  tier_T3: {
    term: "2 teams sign",
    text: "Tier 3. Two approvers from two different teams must sign. The person who proposed it can't sign.",
  },
  tier_T4: {
    term: "Outside SGW",
    text: "Tier 4. Not available in SGW. The system never controls field equipment directly.",
  },
  break_glass: {
    term: "Emergency approval",
    text: "The Incident Commander approves alone, with a written reason. A second team must co-sign within 24 hours. Every emergency approval is reviewed.",
  },
  no_regret: {
    term: "Timing",
    text: "Whether to act now, before the next advisory, or wait. Based on the share of storm scenarios that need this action.",
  },
  no_regret_act_now: {
    term: "Act now",
    text: "Most scenarios need it, or waiting would miss the deadline.",
  },
  no_regret_wait: {
    term: "Can wait",
    text: "The next NHC advisory comes before the earliest deadline, so waiting costs nothing.",
  },
  critical_path: {
    term: "Critical path",
    text: "Steps that must happen in order (1→2→3→4). A delay in any step pulls the final deadline earlier.",
  },
  p50: { term: "Median", text: "Middle estimate: half of the scenarios come out lower, half higher." },
  range80: {
    term: "80% range",
    text: "8 in 10 outcomes should fall inside this range.",
  },
  cone: {
    term: "Storm cone",
    text: "The area the storm's center may cross, about two-thirds of the time. Wind, rain and outages reach well beyond it.",
  },
  advisory: {
    term: "Advisory",
    text: "A forecast update from the National Hurricane Center: full advisories every 6 hours, intermediate ones (like 14A) every 3 hours during watches and warnings.",
  },
  outage_risk: {
    term: "Outage risk",
    text: "Chance that at least 1 in 10 customers in a county lose power at the peak of the storm.",
  },
  wind_gust: {
    term: "Peak gust",
    text: "Strongest gust in the official forecast for each county, in mph.",
  },
  fan: {
    term: "Forecast range",
    text: "Shaded bands show where outcomes could fall: the darkest holds half the scenarios, the next 8 in 10, the lightest 95 in 100.",
  },
  lifelines: {
    term: "Lifelines",
    text: "Services people depend on: power, water pumping, staging yards. Counts show how many sit in high-risk counties.",
  },
  backtest: {
    term: "Track record",
    text: "Past storms run through the forecast without showing it what happened, to check how close it gets.",
  },
  loso: {
    term: "Tested on unseen storms",
    text: "Each storm is forecast by a model built from the other storms only, so it never sees its own result.",
  },
  wind_rule: {
    term: "Wind rule",
    text: "A simple baseline: outages start above a wind speed fitted on the other storms. The forecast must beat it to earn its place.",
  },
  what_if: {
    term: "What-if",
    text: "Reruns the storm with one thing changed, such as its track. Prepared in advance; the real plan doesn't change.",
  },
  synthetic: {
    term: "Synthetic data",
    text: "Made-up data shaped like SGW's real data. Real data replaces it when SGW goes live.",
  },
  mode_strip: {
    term: "Replay mode",
    text: "Replay plays back a past storm on its own clock. All data is synthetic and not for operational use.",
  },
  scope: {
    term: "Coverage",
    text: "The event and service area this view covers. Read-only in this release.",
  },
  queue: {
    term: "Decision list",
    text: 'Open decisions, soonest deadline first. "Waiting on you" shows the ones you can sign now.',
  },
  approval: {
    term: "Signatures",
    text: "Who must sign, who has signed and who is still needed. Signing records your name, role and the plan version.",
  },
  consequence: {
    term: "Impact starts",
    text: "When the impact is expected to begin if nothing is done. The range covers 8 in 10 storm scenarios.",
  },
  lead_time: {
    term: "Lead time",
    text: "How long the action takes once decided. The decide-by time is when impact starts, minus this.",
  },
  slack: {
    term: "Buffer",
    text: 'Time between one step finishing and the next step needing it. "Short by" means the next step will be late.',
  },
  envelope: {
    term: "Pre-approved limits",
    text: "How far the plan may change without new signatures. Changes outside them need a new decision.",
  },
  version_void: {
    term: "Version change",
    text: "A new advisory changed the plan, so earlier signatures no longer count. Review the new version and sign again.",
  },
  ce: {
    term: "Weighted customers",
    text: "Customers affected, weighted by need: a hospital counts for more than a household. The weights are SGW policy.",
  },
  policy_chip: {
    term: "SGW policy",
    text: "A value SGW chose for this exercise, not a regulation. Admin → Policies shows where it comes from.",
  },
  evidence: {
    term: "Evidence",
    text: "The records this recommendation rests on, each with its source. Open one to see where it came from and how fresh it is.",
  },
  ledger: {
    term: "Audit log",
    text: "The permanent record of every decision, signature, and action. Each entry is linked to the one before, so any edit shows.",
  },
  why: {
    term: "Why",
    text: "The advice, up to three reasons, and what would change it.",
  },
  ...HEALTH_GLOSSARY,
  ...WATER_CREWS_GLOSSARY,
  ...AFTERACTION_ADMIN_GLOSSARY,
  ...ASK_BRIEF_GLOSSARY,
  ...ETR_GLOSSARY,
} as const satisfies Record<string, GlossaryEntry>;

export type GlossaryKey = keyof typeof GLOSSARY;

export const tierGlossaryKey = (tier: string): GlossaryKey =>
  (`tier_${tier}` in GLOSSARY ? `tier_${tier}` : "tier_T0") as GlossaryKey;
