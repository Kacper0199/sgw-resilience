import { renderHook } from "@testing-library/react";
import type { DomainFilter, QueueFilter, QueueRow, TimingFilter } from "./queueModel";
import { useQueueTable } from "./useQueueTable";

const row = (id: string, over: Partial<QueueRow>): QueueRow =>
  ({
    id,
    caseId: `DC-${id}`,
    title: `Decision ${id}`,
    domain: "electric",
    owner: { fn: "command", initials: "IC", label: "Incident command" },
    decideByMs: 1,
    severity: "elevated",
    verdict: "decide_now",
    impact: 0,
    pinned: false,
    open: true,
    bucket: "later",
    ...over,
  }) as QueueRow;

const rows = [
  row("a", { domain: "electric" }),
  row("b", { domain: "water", verdict: "act_now" }),
  row("c", { domain: "water", owner: { fn: "water_operations", initials: "WO", label: "Water operations" } }),
  row("d", { open: false }),
];

const base = {
  rows,
  filter: "all" as QueueFilter,
  domain: "all" as DomainFilter,
  owner: "all",
  timing: "all" as TimingFilter,
  find: "",
  sort: "decide" as const,
  desc: false,
  page: 1,
};

const ids = (args: Partial<typeof base>) => {
  const { result } = renderHook(() => useQueueTable({ ...base, ...args }));
  return result.current.getFilteredRowModel().rows.map((r) => r.id);
};

describe("decision filters", () => {
  it("shows every open decision with no filter", () => {
    expect(ids({})).toEqual(["a", "b", "c"]);
  });
  it("filters by utility", () => {
    expect(ids({ domain: "water" })).toEqual(["b", "c"]);
    expect(ids({ domain: "electric" })).toEqual(["a"]);
  });
  it("filters by owner", () => {
    expect(ids({ owner: "water_operations" })).toEqual(["c"]);
  });
  it("filters by timing", () => {
    expect(ids({ timing: "act_now" })).toEqual(["b"]);
  });
  it("filters by search over title and ids", () => {
    expect(ids({ find: "decision b" })).toEqual(["b"]);
    expect(ids({ find: "dc-c" })).toEqual(["c"]);
  });
  it("combines filters", () => {
    expect(ids({ domain: "water", timing: "decide_now" })).toEqual(["c"]);
  });
  it("lists decided decisions only under Decided", () => {
    expect(ids({ filter: "decided" })).toEqual(["d"]);
  });
});
