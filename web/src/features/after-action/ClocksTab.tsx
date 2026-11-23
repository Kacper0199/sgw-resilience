import { History } from "lucide-react";
import { useState } from "react";
import { type DataColumn, DataTable, EmptyState, FilterChip, StatusText } from "@/components/sgw";
import { decisionTitle } from "@/features/decisions/actionTypes";
import { marginText, OUTCOME } from "./format";
import { FLUSH, Stamp, ViewDecision } from "./parts";
import type { ClockOutcome, ClockResult } from "./types";

const FILTERS: { value: "all" | ClockOutcome; label: string }[] = [
  { value: "all", label: "All" },
  { value: "met", label: "Met" },
  { value: "missed", label: "Missed" },
  { value: "open", label: "Still open" },
];

const HOW = { approval: "By signatures", break_glass: "By emergency approval" } as const;

const columns: DataColumn<ClockResult>[] = [
  {
    id: "decision",
    header: "Decision",
    cell: (c) => (
      <span className="block text-[14px] leading-[18px] font-medium">{decisionTitle(c.title)}</span>
    ),
  },
  {
    id: "by",
    header: "Decide by",
    className: "whitespace-nowrap",
    cell: (c) => <Stamp iso={c.effective_decide_by} />,
  },
  {
    id: "decided",
    header: "Decided",
    className: "whitespace-nowrap",
    cell: (c) =>
      c.decided_at ? (
        <>
          <Stamp iso={c.decided_at} utc={false} />
          {c.decided_by && <span className="block text-[12px] text-muted">{HOW[c.decided_by]}</span>}
        </>
      ) : (
        <span className="text-muted">{c.proposed === false ? "No proposal" : "Not decided"}</span>
      ),
  },
  {
    id: "result",
    header: "Result",
    className: "whitespace-nowrap",
    cell: (c) => {
      const o = OUTCOME[c.outcome];
      return (
        <>
          <StatusText level={o.level} label={o.label} />
          {c.margin_min !== null && (
            <span className="block text-[12px] text-muted tnum">{marginText(c.margin_min)}</span>
          )}
        </>
      );
    },
  },
  {
    id: "view",
    header: <span className="sr-only">Open</span>,
    align: "end",
    cell: (c) => (c.proposal_id ? <ViewDecision id={c.proposal_id} /> : null),
  },
];

export function ClocksTab({ clocks }: { clocks: ClockResult[] }) {
  const [filter, setFilter] = useState<"all" | ClockOutcome>("all");
  const shown = [...clocks]
    .filter((c) => filter === "all" || c.outcome === filter)
    .sort((a, b) => Date.parse(a.effective_decide_by) - Date.parse(b.effective_decide_by));
  const n = (o: ClockOutcome) => clocks.filter((c) => c.outcome === o).length;
  return (
    <div className="flex flex-col gap-3">
      <fieldset aria-label="Show" className="m-0 flex flex-wrap gap-2 border-0 p-0">
        {FILTERS.map((f) => (
          <FilterChip
            key={f.value}
            label={`${f.label} ${f.value === "all" ? clocks.length : n(f.value)}`}
            on={filter === f.value}
            onToggle={() => setFilter(f.value)}
          />
        ))}
      </fieldset>
      <div data-testid="clock-table">
        <DataTable
          data={shown}
          columns={columns}
          getRowId={(c) => `${c.decision_case_id}-${c.step}`}
          caption="Deadlines, by decide-by time"
          rowTestId="clock-row"
          className={FLUSH}
          empty={<EmptyState icon={History} title="No deadlines match this filter." />}
        />
      </div>
    </div>
  );
}
