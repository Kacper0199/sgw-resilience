import { TriangleAlert } from "lucide-react";
import { type DataColumn, DataTable, EmptyState, LoadingState } from "@/components/sgw";
import { cn } from "@/lib/cn";
import { isMissing, loadFailureTitle } from "@/lib/loadFailure";
import { ReasonTip } from "../decisions/ReasonTip";
import { useWhatIf } from "./data";
import { withEdges } from "./edge";
import { count, millions } from "./format";
import { SectionHead } from "./SectionHead";
import type { WhatIfCell } from "./types";

const hours = (h: number | null) => (h === null ? "–" : `${h.toFixed(1)} h`);

interface Row extends WhatIfCell {
  id: string;
  title: string;
  baseline: boolean;
}

function Delta({
  now,
  base,
  format,
}: {
  now: number | null;
  base: number | null;
  format: (n: number) => string;
}) {
  if (now === null || base === null) return null;
  const d = now - base;
  if (Math.abs(d) < 1e-9) return <span className="text-muted">same as baseline</span>;
  return <span className="text-muted tnum">{d > 0 ? `+${format(d)}` : `−${format(-d)}`}</span>;
}

const cell = (value: React.ReactNode, delta: React.ReactNode) => (
  <span className="tnum">
    <span className="block">{value}</span>
    <span className="block text-[12px]">{delta}</span>
  </span>
);

function columns(base: WhatIfCell): DataColumn<Row>[] {
  return [
    {
      id: "scenario",
      header: "Scenario",
      cell: (r) => <span className={cn(r.baseline ? "font-semibold" : "font-medium")}>{r.title}</span>,
    },
    {
      id: "peak",
      header: "Peak customers out",
      align: "end",
      cell: (r) =>
        cell(
          millions(r.peak_customers_out),
          !r.baseline && (
            <Delta now={r.peak_customers_out} base={base.peak_customers_out} format={(n) => count(n)} />
          ),
        ),
    },
    {
      id: "hours",
      header: "Customer-hours without power",
      align: "end",
      cell: (r) =>
        cell(
          millions(r.customer_hours),
          !r.baseline && (
            <span className="text-muted">
              {r.delta_customer_hours_pct === 0
                ? "same as baseline"
                : `${r.delta_customer_hours_pct > 0 ? "+" : "−"}${Math.abs(r.delta_customer_hours_pct).toFixed(0)}%`}
            </span>
          ),
        ),
    },
    {
      id: "restore",
      header: "Hours from peak to 90% restored",
      align: "end",
      cell: (r) =>
        cell(
          hours(r.hours_peak_to_90pct),
          !r.baseline && <Delta now={r.hours_peak_to_90pct} base={base.hours_peak_to_90pct} format={hours} />,
        ),
    },
  ];
}

export function WhatIfTab() {
  const whatIf = useWhatIf();
  if (whatIf.isPending) return <LoadingState rows={4} label="Loading the what-ifs" className="px-8 pt-4" />;
  if (whatIf.error && !isMissing(whatIf.error))
    return (
      <EmptyState
        role="alert"
        icon={TriangleAlert}
        title={loadFailureTitle(whatIf.error, "the what-if scenarios")}
      />
    );
  if (!whatIf.data)
    return <EmptyState icon={TriangleAlert} title="The what-if scenarios aren't available yet." />;
  const w = whatIf.data;
  const rows: Row[] = [
    { ...w.baseline, id: "baseline", title: "Baseline: Helene in the what-if model", baseline: true },
    ...w.scenarios.map((s) => ({ ...s, baseline: false })),
  ];
  return (
    <div data-testid="what-if">
      <SectionHead
        className="pt-6"
        title={
          <>
            Three what-ifs against the baseline storm
            <ReasonTip label="About these what-ifs" title="About these what-ifs">
              <p className="m-0">Customer-hours: {w.metric_notes.customer_hours}.</p>
              <p className="m-0">Hours from peak: {w.metric_notes.hours_peak_to_90pct}.</p>
              {w.scenarios.some((s) => s.id === "aid_late") && (
                <p className="m-0">Mutual aid: {w.metric_notes.mutual_aid_request_shift_h}.</p>
              )}
              <p className="m-0">Prepared in advance, one change per row. Nothing here changes the plan.</p>
            </ReasonTip>
          </>
        }
      />
      <p className="m-0 px-8 pb-2 text-[13px] text-muted" data-testid="whatif-basis">
        Whole storm in the what-if model, not this advisory's county forecast, so totals differ.
      </p>
      <DataTable
        caption="What-if scenarios"
        data={rows}
        getRowId={(r) => r.id}
        rowTestId="whatif-row"
        columns={withEdges(columns(w.baseline))}
      />
    </div>
  );
}
