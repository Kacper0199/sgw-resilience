import type { Tier } from "@/contracts/vocab.gen";

const LABEL: Record<Tier, string> = {
  T0: "View only",
  T1: "1 person confirms",
  T2: "1 team signs",
  T3: "2 teams sign",
  T4: "Outside SGW",
};

const DETAIL: Record<Tier, string> = {
  T0: "Nobody signs: information only.",
  T1: "One person confirms before it runs.",
  T2: "One approver signs before it runs.",
  T3: "Two approvers from two different teams sign before it runs.",
  T4: "Decided outside SGW: SGW records it.",
};

/** What an approval tier asks of people, in words: "T3" reads as "2 teams sign". */
export const approvalLabel = (tier: string): string => LABEL[tier as Tier] ?? tier;

/** The same in one plain sentence, for a tooltip. */
export const approvalDetail = (tier: string): string => DETAIL[tier as Tier] ?? approvalLabel(tier);
