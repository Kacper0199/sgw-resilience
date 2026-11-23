import { beforeEach, describe, expect, it } from "vitest";
import type { Asset, ProposalCard } from "@/lib/api";
import { buildChain } from "./chain";
import { describeShift, observeClocks, resetClockShifts, useClockShifts } from "./clockShifts";
import { ADVISORY_TIME, advanceStory, storyCards, summaryOf } from "./mocks/story";
import { compareDecideBy, groupOf, impactOf, type QueueRow, toRows } from "./queueModel";
import { domainFor, ticks } from "./timeAxis";
import { shortDecisionName } from "./ui";
import type { QueueItem } from "./useQueue";
import { observeVersions, resetVoided } from "./voidedApprovals";
import { buildWhy } from "./whyModel";

const itemsAt = (adv: "N" | "N+1"): QueueItem[] =>
  storyCards(adv).map((card) => ({ summary: summaryOf(card), card }));

const me = { function: "command", user_id: "ic_01" } as never;
const row = (over: Partial<QueueRow>): QueueRow =>
  ({ id: "x", open: true, pinned: false, decideByMs: 0, impact: 0, ...over }) as QueueRow;

describe("queue order", () => {
  it("puts closed last, then the signer's own work, then decide-by, then impact", () => {
    const sorted = [
      row({ id: "closed", open: false, decideByMs: 1 }),
      row({ id: "later", decideByMs: 20 }),
      row({ id: "mine-late", pinned: true, decideByMs: 30 }),
      row({ id: "tie-low", decideByMs: 10, impact: 1 }),
      row({ id: "tie-high", decideByMs: 10, impact: 9 }),
    ].sort(compareDecideBy);
    expect(sorted.map((r) => r.id)).toEqual(["mine-late", "tie-high", "tie-low", "later", "closed"]);
  });

  it("ranks impact by critical path, then asset criticality, then customers served", () => {
    const assets = new Map<string, Asset>([
      ["PS-17", { asset_id: "PS-17", criticality: 5, customers_served: 18000 } as Asset],
      ["FDR", { asset_id: "FDR", criticality: 3, customers_served: 90000 } as Asset],
    ]);
    const [ps17, , , , ,] = itemsAt("N");
    const water = { ...ps17, summary: { ...ps17.summary, on_critical_path: false } } as QueueItem;
    const feeder = {
      summary: { ...ps17.summary, on_critical_path: false },
      card: { ...(ps17.card as ProposalCard), target_ids: ["FDR"] },
    } as QueueItem;
    expect(impactOf(water, assets)).toBeGreaterThan(impactOf(feeder, assets));
    expect(impactOf(ps17 as QueueItem, assets)).toBeGreaterThan(impactOf(water, assets));
  });

  it("groups the signer's own decisions apart from the time buckets", () => {
    const rows = toRows(itemsAt("N"), me, ADVISORY_TIME.N, new Map());
    const keys = Object.fromEntries(rows.map((r) => [r.id, groupOf(r)]));
    expect(keys["PRP-PS17-FDR2207-PRIO"]).toBe("mine");
    expect(keys["PRP-SITREP-PRELANDFALL"]).toBe("mine");
    expect(keys["PRP-CREW-AIK-0926A"]).not.toBe("mine");
    expect(keys["PRP-AIK-STAGE"]).toBe("hour");
  });

  it("moves PS-17 above the situation report at advisory N+1 and pins the voided crew decision", () => {
    const at = (adv: "N" | "N+1") =>
      toRows(itemsAt(adv), me, ADVISORY_TIME[adv], new Map())
        .sort(compareDecideBy)
        .map((r) => r.id);
    expect(at("N").slice(0, 2)).toEqual(["PRP-SITREP-PRELANDFALL", "PRP-PS17-FDR2207-PRIO"]);
    expect(at("N+1").slice(0, 3)).toEqual([
      "PRP-CREW-AIK-0926A",
      "PRP-PS17-FDR2207-PRIO",
      "PRP-SITREP-PRELANDFALL",
    ]);
  });
});

describe("critical chain", () => {
  it("numbers prerequisites first and gives the link a positive slack at N+1", () => {
    const chain = buildChain(itemsAt("N+1"), "PRP-PS17-FDR2207-PRIO", ADVISORY_TIME["N+1"]);
    expect(chain.steps.map((s) => [s.n, s.item.summary.proposal_id])).toEqual([
      [1, "PRP-CREW-AIK-0926A"],
      [2, "PRP-PS17-FDR2207-PRIO"],
    ]);
    expect(chain.steps[1]?.incoming).toEqual([{ from: 1, slackMin: 424 }]);
    expect(chain.blockedBy.map((i) => i.summary.proposal_id)).toEqual(["PRP-CREW-AIK-0926A"]);
    expect(chain.blocks).toEqual([]);
  });

  it("gives the other side of the link from the prerequisite", () => {
    const chain = buildChain(itemsAt("N+1"), "PRP-CREW-AIK-0926A", ADVISORY_TIME["N+1"]);
    expect(chain.blocks.map((i) => i.summary.proposal_id)).toEqual(["PRP-PS17-FDR2207-PRIO"]);
    expect(chain.blockedBy).toEqual([]);
  });

  it("makes the slack negative when the prerequisite can no longer finish in time", () => {
    const chain = buildChain(itemsAt("N+1"), "PRP-PS17-FDR2207-PRIO", "2024-09-26T23:30:00Z");
    expect(chain.steps[1]?.incoming[0]?.slackMin).toBeLessThan(0);
  });

  it("gives every prerequisite of a step its own slack and marks the late one", () => {
    const items = itemsAt("N+1").map((i) =>
      i.summary.proposal_id === "PRP-PS17-FDR2207-PRIO" && i.card
        ? {
            ...i,
            card: {
              ...i.card,
              case: { ...i.card.case, prerequisite_ids: ["DC-D2-CREWS-AIK", "DC-D1-MUTUAL-AID"] },
            },
          }
        : i,
    );
    const chain = buildChain(items, "PRP-PS17-FDR2207-PRIO", "2024-09-26T23:00:00Z");
    const ps17 = chain.steps.find((s) => s.item.summary.proposal_id === "PRP-PS17-FDR2207-PRIO");
    expect(chain.steps).toHaveLength(3);
    expect(ps17?.incoming).toHaveLength(2);
    const byFrom = Object.fromEntries((ps17?.incoming ?? []).map((l) => [l.from, l.slackMin]));
    const crewsStep = chain.steps.find((s) => s.item.summary.proposal_id === "PRP-CREW-AIK-0926A")?.n ?? 0;
    const aidStep = chain.steps.find((s) => s.item.summary.proposal_id === "PRP-MUTUAL-AID")?.n ?? 0;
    expect(byFrom[crewsStep]).toBe(-31);
    expect(byFrom[aidStep]).toBe(29);
  });

  it("has no chain for a decision outside it", () => {
    const chain = buildChain(itemsAt("N"), "PRP-MUTUAL-AID", ADVISORY_TIME.N);
    expect(chain).toEqual({ steps: [], blockedBy: [], blocks: [] });
  });
});

describe("why block", () => {
  const card = (id: string, adv: "N" | "N+1") =>
    storyCards(adv).find((c) => c.proposal_id === id) as ProposalCard;

  it("gives the agreement as a percentage of cases and drops the synthetic marker sentence", () => {
    const why = buildWhy(card("PRP-PS17-FDR2207-PRIO", "N+1"));
    expect(why.verdictLabel).toBe("Act now");
    expect(why.agreement).toBe("91% of cases");
    expect(why.reasons.length).toBeLessThanOrEqual(3);
    expect(why.reasons.join(" ")).not.toMatch(/Synthetic data/);
    expect(why.limit).toMatch(/17:00 ET/);
  });

  it("has no verdict line when no verdict applies", () => {
    const why = buildWhy(card("PRP-CREW-AIK-0926A", "N"));
    expect(why.verdictLabel).toBeNull();
    expect(why.agreement).toBeNull();
  });
});

describe("clock shifts", () => {
  beforeEach(() => resetClockShifts());
  it("describes the PS-17 move as earlier by 1 h 16 m", () => {
    observeClocks(itemsAt("N"));
    observeClocks(itemsAt("N+1"));
    const state = JSON.parse(sessionStorage.getItem("sgw.clockShifts") ?? "{}");
    expect(describeShift(state["DC-D3-PS17-POWER"]).text).toBe("Earlier by 1 h 16 m, was 00:45 ET (04:45Z)");
  });
  it("records nothing when a clock does not move", () => {
    observeClocks(itemsAt("N"));
    observeClocks(itemsAt("N"));
    expect(sessionStorage.getItem("sgw.clockShifts")).toBeNull();
  });
  it("exposes the hook shape", () => {
    expect(typeof useClockShifts).toBe("function");
  });
});

describe("voided signatures", () => {
  beforeEach(() => resetVoided());
  it("keeps a signature that disappeared when a new version arrived", () => {
    observeVersions(itemsAt("N"));
    observeVersions(itemsAt("N+1"));
    const stored = JSON.parse(sessionStorage.getItem("sgw.voidedApprovals") ?? "{}");
    expect(stored["PRP-CREW-AIK-0926A"]).toEqual([
      expect.objectContaining({ approver_id: "ic_01", version: 1, voidedBy: 2 }),
    ]);
  });
});

describe("time axis", () => {
  it("keeps Now inside the axis when it is within twelve hours of the decide-by range", () => {
    const hour = 3_600_000;
    const { domain, nowOutside } = domainFor(10 * hour, 12 * hour, 16 * hour);
    expect(nowOutside).toBe(false);
    expect(domain.start).toBeLessThan(10 * hour);
  });
  it("pins Now to the edge and flags it when it is much earlier", () => {
    const hour = 3_600_000;
    const { domain, nowOutside } = domainFor(0, 20 * hour, 24 * hour);
    expect(nowOutside).toBe(true);
    expect(domain.start).toBeGreaterThan(0);
  });
  it("gives at most four whole-hour ticks with ET and Z labels", () => {
    const start = Date.parse("2024-09-27T00:00:00Z");
    const t = ticks({ start, end: start + 12 * 3_600_000 });
    expect(t.length).toBeLessThanOrEqual(4);
    expect(t[0]).toMatchObject({ z: "00:00Z", et: "Sep 26 20:00" });
  });
  it("names the day on the ticks when the axis crosses midnight ET", () => {
    const start = Date.parse("2024-09-27T00:00:00Z");
    expect(ticks({ start, end: start + 3 * 3_600_000 }).map((t) => t.et)).toEqual([
      "20:00",
      "21:00",
      "22:00",
      "23:00",
    ]);
    const long = ticks({ start, end: start + 36 * 3_600_000 });
    expect(long.map((t) => t.et)).toEqual(["Sep 26 20:00", "Sep 27 08:00", "20:00", "Sep 28 08:00"]);
    const twoDays = ticks({ start: start - 3_600_000, end: start + 47 * 3_600_000 });
    expect(twoDays.map((t) => t.et)).toEqual(["Sep 26 20:00", "Sep 27 20:00"]);
  });
});

describe("story", () => {
  it("advances the mock world to N+1 and announces the clock and the version change", () => {
    const cards = storyCards("N");
    const emitted: string[] = [];
    const scenario = { scenario_time: ADVISORY_TIME.N };
    advanceStory("N+1", { cards, scenario, emit: (type) => emitted.push(type) });
    const crews = cards.find((c) => c.proposal_id === "PRP-CREW-AIK-0926A");
    expect(crews?.proposal_version).toBe(2);
    expect(crews?.approvals).toEqual([]);
    expect(scenario.scenario_time).toBe(ADVISORY_TIME["N+1"]);
    expect(emitted).toEqual([
      "ScenarioClockChanged",
      "DecisionClockUpdated",
      "DecisionClockUpdated",
      "ProposalUpdated",
    ]);
  });
});

describe("shortDecisionName", () => {
  it("drops the verb and puts a station first", () => {
    expect(shortDecisionName("Hook up the portable generator at PS-17")).toBe("PS-17 portable generator");
    expect(shortDecisionName("Dispatch the fuel truck to PS-17")).toBe("PS-17 fuel truck");
  });
  it("keeps a multi-word place and shortens long names", () => {
    expect(shortDecisionName("Pre-position crews at Sandhill and Millpond yards")).toBe(
      "crews at Sandhill and Millpond yards",
    );
  });
});
