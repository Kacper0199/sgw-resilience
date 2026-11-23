import { ArrowRight, GitCompareArrows } from "lucide-react";
import { type DataColumn, DataTable, EmptyState, LoadingState, Sparkline } from "@/components/sgw";
import { isMissing, loadFailureTitle } from "@/lib/loadFailure";
import { VerdictText } from "../decisions/VerdictText";
import { DecisionRefs } from "./DecisionLink";
import { useCountyForecast, usePlanDiff } from "./data";
import { withEdges } from "./edge";
import { count, countyLabel, ofForty, signed } from "./format";
import { SectionHead } from "./SectionHead";
import type { PlanDiffAction, PlanDiffCounty } from "./types";

const BAND: Record<string, string> = {
  very_low: "Very low",
  low: "Low",
  moderate: "Moderate",
  high: "High",
  very_high: "Very high",
};

function Move({ from, to }: { from: number; to: number }) {
  return (
    <span className="inline-flex items-center gap-1.5 tnum">
      <span className="text-muted">{count(from)}</span>
      <ArrowRight className="size-3.5 text-muted" aria-hidden />
      <span className="font-semibold">{count(to)}</span>
    </span>
  );
}

interface Measure {
  id: string;
  label: string;
  values: [number, number] | null;
  assets?: number;
}

const COUNTY_COLUMNS: DataColumn<PlanDiffCounty>[] = [
  {
    id: "county",
    header: "County",
    cell: (c) => <span className="font-medium">{countyLabel(c.name, c.fips)}</span>,
    sort: (a, b) => a.name.localeCompare(b.name),
  },
  {
    id: "median",
    header: "Median (customers)",
    align: "end",
    cell: (c) => <Move from={c.p50_out[0]} to={c.p50_out[1]} />,
    sort: (a, b) => a.p50_out[1] - b.p50_out[1],
  },
  {
    id: "high",
    header: "High end (80%)",
    align: "end",
    cell: (c) => <Move from={c.p90_out[0]} to={c.p90_out[1]} />,
    sort: (a, b) => a.p90_out[1] - b.p90_out[1],
  },
  {
    id: "risk",
    header: "Risk",
    cell: (c) => (
      <span>
        {BAND[c.band[0]] ?? c.band[0]}
        {c.band[0] !== c.band[1] && <> to {BAND[c.band[1]] ?? c.band[1]}</>}
      </span>
    ),
  },
];

function share(a: PlanDiffAction, members: number | null): [string, string] {
  const fmt = (ppm: number) =>
    members ? `${ofForty(ppm, members)} scenarios` : `${Math.round(ppm / 10_000)}%`;
  return [a.share_ppm[0] === null ? "new" : fmt(a.share_ppm[0]), fmt(a.share_ppm[1])];
}

function measureColumns(): DataColumn<Measure>[] {
  return [
    { id: "measure", header: "Measure", cell: (m) => m.label },
    {
      id: "from",
      header: "Previous advisory",
      align: "end",
      cell: (m) => <span className="tnum text-muted">{m.values ? count(m.values[0]) : "–"}</span>,
    },
    {
      id: "to",
      header: "Latest advisory",
      align: "end",
      cell: (m) => <span className="tnum font-semibold">{m.values ? count(m.values[1]) : "–"}</span>,
    },
    {
      id: "change",
      header: "Change",
      align: "end",
      cell: (m) => (
        <span className="tnum" data-testid="delta">
          {m.values ? signed(m.values[1] - m.values[0]) : `${count(m.assets ?? 0)} assets`}
        </span>
      ),
    },
  ];
}

export function PlanChangeTab({ advisory }: { advisory: string | null }) {
  const diff = usePlanDiff(advisory);
  const forecast = useCountyForecast(advisory);
  if (diff.isLoading && advisory !== null) {
    return <LoadingState rows={5} label="Loading what changed" className="px-8 pt-4" />;
  }
  if (diff.error && !isMissing(diff.error)) {
    return (
      <EmptyState role="alert" icon={GitCompareArrows} title={loadFailureTitle(diff.error, "what changed")} />
    );
  }
  if (!diff.data) {
    return <EmptyState icon={GitCompareArrows} title="First advisory: nothing earlier to compare." />;
  }
  const d = diff.data;
  const members = forecast.data?.members ?? null;
  const line = members
    ? ofForty(d.act_now_threshold_ppm, members)
    : `${Math.round(d.act_now_threshold_ppm / 10_000)}%`;
  const measures: Measure[] = [
    {
      id: "mean",
      label: "Customers out at the peak, average of all scenarios",
      values: d.footprint_mean_out,
    },
  ];
  const actionColumns: DataColumn<PlanDiffAction>[] = [
    {
      id: "decision",
      header: "Decision",
      cell: (a) => (
        <div className="py-1">
          <div className="font-medium">{a.label}</div>
          <div className="mt-0.5">
            <DecisionRefs caseIds={a.decision_case_ids} />
          </div>
        </div>
      ),
    },
    {
      id: "share",
      header: "Scenarios that need it",
      cell: (a) => {
        const [from, to] = share(a, members);
        const past = a.crossed_act_now_threshold;
        const values = a.share_ppm[0] === null ? [] : [a.share_ppm[0], a.share_ppm[1]];
        return (
          <span className="inline-flex items-center gap-3 tnum">
            <span className="inline-flex items-center gap-1.5">
              <span className="text-muted">{from}</span>
              <ArrowRight className="size-3.5 text-muted" aria-hidden />
              <span className="font-semibold">{to}</span>
            </span>
            {values.length === 2 && (
              <Sparkline
                values={values}
                limit={d.act_now_threshold_ppm}
                tone={past ? "warn" : "neutral"}
                width={56}
                label="Scenarios that need it, previous to latest advisory"
              />
            )}
          </span>
        );
      },
    },
    {
      id: "timing",
      header: "Timing now",
      cell: (a) => (
        <div className="py-1">
          {a.timing ? (
            <VerdictText verdict={a.timing} />
          ) : (
            <span className="text-muted">No open decision</span>
          )}
          <div
            className="mt-0.5 text-[12px] text-muted"
            data-testid={a.crossed_act_now_threshold ? "crossed" : undefined}
          >
            {a.share_ppm[1] < d.act_now_threshold_ppm
              ? `Below the act-now share (${line})`
              : a.timing === "act_now" || !a.timing
                ? `Above the act-now share (${line})`
                : `Needed in ${members ? ofForty(a.share_ppm[1], members) : `${Math.round(a.share_ppm[1] / 10_000)}%`} scenarios`}
          </div>
        </div>
      ),
    },
  ];
  return (
    <div data-testid="plan-change">
      <SectionHead className="pt-6" title="What changed since the previous advisory" />
      <DataTable
        compact
        caption="What changed since the previous advisory"
        data={measures}
        getRowId={(m) => m.id}
        columns={withEdges(measureColumns())}
      />
      <SectionHead title="Plan steps" info="no_regret" />
      <DataTable
        caption="Plan steps"
        data={d.actions}
        getRowId={(a) => a.action_id}
        rowTestId="plan-action"
        columns={withEdges(actionColumns)}
      />
      <SectionHead title="Biggest county changes" />
      <DataTable
        compact
        caption="Biggest county changes"
        data={d.counties}
        getRowId={(c) => c.fips}
        columns={withEdges(COUNTY_COLUMNS)}
      />
    </div>
  );
}
