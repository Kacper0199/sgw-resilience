/** Scenarios other than the Helene replay: scripted exercise packs. Pages without a model for a pack show a plain state. */
export const SCENARIO_PACKS = {
  ian: { title: "Hurricane Ian", period: "September 2022" },
} as const;

export type PackId = keyof typeof SCENARIO_PACKS;

export const isPack = (scenario: string | undefined | null): scenario is PackId =>
  scenario != null && Object.hasOwn(SCENARIO_PACKS, scenario);

/** Helene-only pages that also read a scripted exercise (they leave the not-modelled gate). */
export const PACK_PAGES: ReadonlySet<string> = new Set(["crews", "after_action"]);
