import { Target } from "lucide-react";
import { type DataColumn, DataTable, EmptyState, InfoTip, SourceLine } from "@/components/sgw";
import { formatEtZ } from "@/lib/time";
import { errorText, hours, regionLabel, share } from "./format";
import { FLUSH } from "./parts";
import type { Scorecard, ScoreEstimate, ScoreMetric } from "./types";

const metric = (card: Scorecard, suffix: string): ScoreMetric | undefined =>
  card.metrics.find((m) => m.metric.endsWith(suffix));

function ErrorBars({ e, max }: { e: ScoreEstimate; max: number }) {
  if (e.abs_error_h === null || e.analog_abs_error_h === null) return <span className="text-muted">–</span>;
  const ours = (e.abs_error_h / max) * 100;
  const analog = (e.analog_abs_error_h / max) * 100;
  return (
    <div
      role="img"
      aria-label={`ETR off by ${hours(e.abs_error_h)}; past-storm average off by ${hours(e.analog_abs_error_h)}`}
      className="flex w-full min-w-[96px] flex-col gap-1"
    >
      <span className="block h-1.5 bg-primary" style={{ width: `${ours}%` }} />
      <span className="block h-1.5 bg-hair-strong" style={{ width: `${analog}%` }} />
    </div>
  );
}

const yesNo = (b: boolean | null) => (b === null ? "–" : b ? "Yes" : "No");

function Stat({
  label,
  value,
  info,
}: {
  label: string;
  value: string;
  info?: "analog_baseline" | "range80";
}) {
  return (
    <div className="min-w-0 border-l border-divider pl-4 first:border-l-0 first:pl-0">
      <dt className="flex items-center gap-1 text-[12px] font-semibold text-muted">
        {label}
        {info && <InfoTip term={info} />}
      </dt>
      <dd className="m-0 text-[22px] leading-7 font-semibold tnum">{value}</dd>
    </div>
  );
}

export function ScorecardTab({ card }: { card: Scorecard | null }) {
  if (!card || card.estimates.length === 0)
    return <EmptyState icon={Target} title="No published estimate to compare yet." />;
  if (card.estimates.every((e) => e.actual_utc === null))
    return <EmptyState icon={Target} title="Accuracy is known once power is restored." />;
  const global = metric(card, "global.p50_abs_error_h_median");
  const areas = metric(card, "region.p50_abs_error_h_median");
  const inner = metric(card, "region.within_p25_p75");
  const outer = metric(card, "region.within_p10_p90");
  const max = Math.max(
    1e-9,
    ...card.estimates.map((e) => Math.max(e.abs_error_h ?? 0, e.analog_abs_error_h ?? 0)),
  );
  const ordered = [...card.estimates].sort((a, b) =>
    a.scope === b.scope ? (a.abs_error_h ?? 0) - (b.abs_error_h ?? 0) : a.scope === "global" ? -1 : 1,
  );
  const first = card.estimates[0];
  const columns: DataColumn<ScoreEstimate>[] = [
    {
      id: "area",
      header: "Area",
      cell: (e) => (
        <span className={e.scope === "global" ? "font-semibold" : "font-mono text-[12px]"}>
          {regionLabel(e.region_id)}
        </span>
      ),
    },
    {
      id: "was",
      header: "Estimate was",
      className: "whitespace-nowrap tnum",
      cell: (e) => (e.p50_error_h === null ? "Not known yet" : errorText(e.p50_error_h)),
    },
    {
      id: "bars",
      header: "Compared with past storms",
      className: "w-40",
      cell: (e) => <ErrorBars e={e} max={max} />,
    },
    { id: "r50", header: "50% range", cell: (e) => yesNo(e.in_p25_p75) },
    { id: "r80", header: "80% range", cell: (e) => yesNo(e.in_p10_p90) },
    {
      id: "actual",
      header: "Actual",
      className: "whitespace-nowrap text-muted tnum",
      cell: (e) => (e.actual_utc === null ? "–" : formatEtZ(e.actual_utc)),
    },
  ];
  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 flex items-center gap-1 text-[13px] text-muted">
        Each estimate compared with what happened.
        <InfoTip term="scorecard" />
      </p>
      <dl className="m-0 grid grid-cols-2 gap-y-3 min-[700px]:grid-cols-4">
        {global && (
          <Stat label="Error, whole service area" value={hours(global.value)} info="analog_baseline" />
        )}
        {areas && <Stat label={`Typical error, ${areas.n} areas`} value={hours(areas.value)} />}
        {inner && <Stat label="Areas inside the 50% range" value={share(inner.value)} />}
        {outer && <Stat label="Areas inside the 80% range" value={share(outer.value)} info="range80" />}
      </dl>
      {(global?.baseline_value != null || areas?.baseline_value != null) && (
        <p className="m-0 text-[13px] text-muted" data-testid="analog-line">
          Past-storm average, for comparison:
          {global?.baseline_value != null && ` ${hours(global.baseline_value)} for the whole service area`}
          {areas?.baseline_value != null && `, ${hours(areas.baseline_value)} typical for areas`}.
        </p>
      )}
      <div data-testid="score-table" className="overflow-x-auto">
        <DataTable
          data={ordered}
          columns={columns}
          getRowId={(e) => e.estimate_id}
          caption="ETRs vs. simulated actual"
          rowTestId="score-row"
          className={FLUSH}
          compact
        />
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-1.5 w-5 bg-primary" aria-hidden /> SGW estimate error
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-1.5 w-5 bg-hair-strong" aria-hidden /> Past-storm average error
        </span>
      </div>
      <SourceLine>
        {`Estimates from ${formatEtZ(first?.as_of_utc ?? "")}. Actual: ${card.actual_label}. Synthetic data from one storm: a description, not proof of accuracy.`}
      </SourceLine>
    </div>
  );
}
