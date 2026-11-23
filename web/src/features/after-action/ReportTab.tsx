import { Download, FileText, OctagonAlert } from "lucide-react";
import { type DataColumn, DataTable, EmptyState, InfoTip, SourceLine, Tag } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { useRegions } from "@/features/map/data";
import { formatDayET, formatET } from "@/lib/time";
import { count, hours } from "./format";
import { FLUSH } from "./parts";
import type { InterruptionRecord, ScReport } from "./types";

export const EXERCISE_FOOTER = "Exercise with synthetic data, not for operational use";

const at = (iso: string) => `${formatDayET(iso)}, ${formatET(iso)}`;

function download(report: ScReport) {
  const url = URL.createObjectURL(new Blob([report.markdown], { type: "text/markdown" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "sc-103-314-draft.md";
  a.click();
  URL.revokeObjectURL(url);
}

/** Rows shown in the counties table; the rest travel in the downloaded draft. */
const SHOWN = 15;

/** "SC-SYSTEM" is the whole service area, "SC-45083" the county with that FIPS code. */
function useAreaName(): (r: InterruptionRecord) => string {
  const regions = useRegions();
  return (r) => {
    if (r.area_kind === "system") return "Whole SC service area";
    const fips = r.area_id.replace(/^SC-/, "");
    return regions.data?.find((g) => g.county_fips === fips)?.name ?? r.area_id;
  };
}

function Rows({
  rows,
  threshold,
  caption,
  flagged = true,
}: {
  rows: InterruptionRecord[];
  threshold: number;
  caption: string;
  flagged?: boolean;
}) {
  const areaName = useAreaName();
  const columns: DataColumn<InterruptionRecord>[] = [
    {
      id: "area",
      header: "Area",
      cell: (r) => <span title={r.area_id}>{areaName(r)}</span>,
    },
    { id: "started", header: "Started", className: "whitespace-nowrap tnum", cell: (r) => at(r.started_at) },
    {
      id: "restored",
      header: "Restored",
      className: "whitespace-nowrap tnum",
      cell: (r) => at(r.restored_at),
    },
    {
      id: "duration",
      header: "Duration",
      className: "whitespace-nowrap tnum",
      cell: (r) => hours(r.duration_h),
    },
    { id: "customers", header: "Customers", className: "tnum", cell: (r) => count(r.customers_interrupted) },
    ...(flagged
      ? [
          {
            id: "required",
            header: `Over ${threshold} hours`,
            cell: (r: InterruptionRecord) => (r.report_required ? "Yes" : "No"),
          },
        ]
      : []),
  ];
  return (
    <div className="overflow-x-auto">
      <DataTable
        data={rows}
        columns={columns}
        getRowId={(r) => r.area_id}
        caption={caption}
        rowTestId="report-row"
        className={FLUSH}
        compact
      />
    </div>
  );
}

export function ReportTab({ report, chainOk }: { report: ScReport | null; chainOk: boolean }) {
  if (!report)
    return <EmptyState icon={FileText} title="No report draft yet. It is created after power is restored." />;
  const reportable = report.counties.filter((r) => r.report_required);
  const more = reportable.length - SHOWN;
  return (
    <article className="flex flex-col gap-5" data-testid="sc-report">
      {!chainOk && (
        <p role="alert" className="m-0 flex items-center gap-2 text-[14px] font-semibold text-crit">
          <OctagonAlert className="size-4 shrink-0" aria-hidden />
          Do not use: the audit log failed its check, so this draft cannot be trusted.
        </p>
      )}
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="m-0 flex items-center gap-1 text-[15px] font-bold">
            {report.event_name}: interruption report draft
            <InfoTip term="sc_report" />
          </h3>
          <p className="m-0 mt-0.5 text-[13px] text-muted">{report.citation}</p>
        </div>
        <div className="flex items-center gap-3">
          <Tag>Draft, not filed</Tag>
          <Button variant="secondary" onClick={() => download(report)}>
            <Download aria-hidden />
            Download draft
          </Button>
        </div>
      </header>
      <section className="flex flex-col gap-2">
        <h4 className="m-0 border-b border-hair pb-1.5 text-[15px] font-bold">From SGW records</h4>
        <Rows
          rows={[report.system]}
          threshold={report.threshold_h}
          caption="System-wide interruption record"
        />
      </section>
      <section className="flex flex-col gap-2">
        <h4 className="m-0 border-b border-hair pb-1.5 text-[15px] font-bold">
          Counties over {report.threshold_h} hours ({reportable.length} of {report.counties.length})
        </h4>
        <Rows
          rows={reportable.slice(0, SHOWN)}
          threshold={report.threshold_h}
          caption="Counties over the reporting threshold"
          flagged={false}
        />
        {more > 0 && <SourceLine>{`${more} more counties are in the attached file.`}</SourceLine>}
      </section>
      {report.filer_notes?.length ? (
        <section className="flex flex-col gap-2">
          <h4 className="m-0 border-b border-hair pb-1.5 text-[15px] font-bold">For the person filing</h4>
          <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-[14px]">
            {report.filer_notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </section>
      ) : null}
      <SourceLine>{`${report.label} ${EXERCISE_FOOTER}.`}</SourceLine>
    </article>
  );
}
