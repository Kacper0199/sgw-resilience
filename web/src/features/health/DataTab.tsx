import { ChevronRight, Database } from "lucide-react";
import { useState } from "react";
import { CountBadge, type DataColumn, DataTable, EmptyState, StatusText, Tag } from "@/components/sgw";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/cn";
import { isPack } from "@/lib/scenarios";
import { useScenario } from "@/sse/useScenarioNow";
import { Failed, Loading } from "./Async";
import { withEdges } from "./edge";
import {
  ageText,
  assetLabel,
  dayTime,
  FEED_MODE_LABEL,
  feedName,
  feedStatus,
  humanize,
  list,
  measured,
  PLATFORM_CLOCK,
  platformTime,
  plural,
  sentence,
  tookText,
} from "./format";
import { RunNow } from "./RunNow";
import { SectionHead } from "./SectionHead";
import { Mark, StatusLine, type Tone } from "./Status";
import { TH } from "./tables";
import type { DqCheck, FeedHealthItem, PipelineAsset, PipelineRun } from "./types";
import { useAssets, useChecks, useFeeds, usePipelineRuns } from "./useHealth";

const RUN_TONE: Record<PipelineRun["status"], { tone: Tone; label: string }> = {
  success: { tone: "ok", label: "Done" },
  partial: { tone: "warn", label: "Partly done" },
  failed: { tone: "bad", label: "Failed" },
  running: { tone: "idle", label: "Running" },
};

function Summary() {
  const feeds = useFeeds();
  const checks = useChecks();
  if (feeds.isPending || checks.isPending)
    return (
      <StatusLine tone="idle" headline="Loading data status…" detail="Sources and checks are loading." />
    );
  if (feeds.error || checks.error)
    return <StatusLine tone="bad" headline="Couldn't load data status." detail="Try again in a moment." />;
  const late = feeds.data.filter((f) => f.stale);
  const failed = checks.data.filter((c) => !c.passed && c.severity === "error");
  const warned = checks.data.filter((c) => !c.passed && c.severity === "warn");
  if (feeds.data.length === 0 && checks.data.length === 0)
    return (
      <StatusLine tone="idle" headline="No data yet." detail="Sources appear after the first data load." />
    );
  if (late.length || failed.length) {
    const parts = [
      late.length ? `Late: ${list(late.map(feedName))}.` : "",
      failed.length ? `${plural(failed.length, "data check")} failed.` : "",
    ];
    return (
      <StatusLine
        tone={failed.length ? "bad" : "warn"}
        headline="Some data needs attention."
        detail={parts.filter(Boolean).join(" ")}
      />
    );
  }
  if (warned.length === 0) return null;
  return (
    <StatusLine
      tone="warn"
      headline="Data is up to date, with warnings."
      detail={`${plural(feeds.data.filter((f) => feedStatus(f) === "on_time").length, "source")} on time. ${plural(checks.data.length - warned.length, "data check")} passed, ${plural(warned.length, "warning")}.`}
    />
  );
}

/** Bar against the accepted age: track, fill (blue; amber when over), a tick at the limit. The bar ends at twice the limit. */
function LimitBar({ feed }: { feed: FeedHealthItem }) {
  const age = measured(feed).seconds;
  if (age === null) return <span className="text-faint">–</span>;
  const fill = Math.min(1, age / (feed.freshness_limit_s * 2));
  return (
    <span
      role="img"
      aria-label={`Data age ${ageText(age)} of ${ageText(feed.freshness_limit_s)} accepted`}
      className="relative block h-1.5 w-[150px] rounded-full bg-hair"
    >
      <span
        className={cn(
          "absolute inset-y-0 left-0 rounded-full",
          feed.stale ? "bg-warn-mark" : "bg-[var(--chart-1)]",
        )}
        style={{ width: `${fill * 100}%` }}
      />
      <span className="absolute -top-1 bottom-[-4px] left-1/2 w-0.5 bg-ink" />
    </span>
  );
}

const FEED_COLUMNS: DataColumn<FeedHealthItem>[] = [
  {
    id: "source",
    header: "Source",
    cell: (f) => (
      <span className="font-medium" title={f.source_id}>
        {feedName(f)}
      </span>
    ),
  },
  {
    id: "status",
    header: "Status",
    cell: (f) => {
      const status = feedStatus(f);
      return status === "late" ? (
        <StatusText level="elevated" label="Late" />
      ) : status === "no_data" ? (
        <StatusText level="unknown_stale" label="No data yet" />
      ) : status === "quiet" ? (
        <span className="text-muted" title="Reports only when something changes.">
          No changes yet
        </span>
      ) : (
        <StatusText level="normal" label="On time" />
      );
    },
  },
  {
    id: "age",
    header: "Age",
    cell: (f) =>
      feedStatus(f) === "quiet" ? (
        <span className="text-faint">–</span>
      ) : (
        <span className={cn("font-semibold tnum", f.stale && "text-warn")}>{measured(f).text}</span>
      ),
  },
  { id: "bar", header: "Against the limit", cell: (f) => <LimitBar feed={f} /> },
  {
    id: "limit",
    header: "Max age",
    cell: (f) => <span className="text-muted tnum">{ageText(f.freshness_limit_s)}</span>,
  },
  { id: "mode", header: "Load type", cell: (f) => <Tag>{FEED_MODE_LABEL[f.feed_mode]}</Tag> },
];

function FeedsTable() {
  const feeds = useFeeds();
  if (feeds.isPending) return <Loading what="data sources" />;
  if (feeds.error) return <Failed what="Data sources" error={feeds.error} />;
  if (feeds.data.length === 0)
    return <EmptyState icon={Database} title="No data sources yet." className="py-6" />;
  return (
    <DataTable
      caption="Data sources"
      data={feeds.data}
      getRowId={(f) => f.source_id}
      rowTestId="feed-row"
      compact
      columns={withEdges(
        new Set(feeds.data.map((f) => f.feed_mode)).size > 1
          ? FEED_COLUMNS
          : FEED_COLUMNS.filter((c) => c.id !== "mode"),
      )}
    />
  );
}

function Chips({ ids, none }: { ids: string[]; none: string }) {
  if (ids.length === 0) return <span className="text-muted">{none}</span>;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {ids.map((id) => (
        <span key={id} className="rounded-sm bg-surface-3 px-1.5 py-0.5 text-[12px]" title={id}>
          {assetLabel(id).name}
        </span>
      ))}
    </span>
  );
}

function AssetRow({ asset }: { asset: PipelineAsset }) {
  const [open, setOpen] = useState(false);
  const run = asset.last_run;
  const tone = run ? RUN_TONE[run.status] : null;
  const dqProblem = run ? run.dq.errors + run.dq.warnings : 0;
  const label = assetLabel(asset.name, asset.description);
  return (
    <>
      <tr className="border-b border-hair" data-testid="asset-row">
        <td className="px-8 py-2 align-top">
          <span className="block text-[14px] font-medium">{label.name}</span>
          <span className="block max-w-[320px] text-[12px] text-muted" title={asset.name}>
            {label.text}
          </span>
        </td>
        <td className="px-3 py-2 align-top">
          {run?.skipped ? (
            <span className="text-muted">Built with the demo</span>
          ) : run && tone ? (
            <>
              <Mark tone={tone.tone}>{tone.label}</Mark>
              <span
                className="block text-[12px] text-muted tnum"
                title={run.replay ? platformTime(run.started_at) : PLATFORM_CLOCK}
              >
                {run.replay ? "When the demo was built" : platformTime(run.started_at)}
              </span>
            </>
          ) : (
            <span className="text-muted">Not loaded yet</span>
          )}
        </td>
        <td className="px-3 py-2 align-top tnum">
          {run && !run.skipped ? (
            <>
              {run.rows_out.toLocaleString("en-US")} rows
              {run.rows_quarantined > 0 && (
                <span className="block text-[12px] text-warn">
                  {run.rows_quarantined.toLocaleString("en-US")} held back
                </span>
              )}
            </>
          ) : (
            "–"
          )}
        </td>
        <td className="px-3 py-2 align-top">
          {run && !run.skipped ? (
            dqProblem === 0 ? (
              <Mark tone="ok">{plural(run.dq.checks, "check")} passed</Mark>
            ) : (
              <Mark tone={run.dq.errors ? "bad" : "warn"}>
                {run.dq.errors ? `${dqProblem} failed` : plural(dqProblem, "warning")}
              </Mark>
            )
          ) : (
            "–"
          )}
        </td>
        <td className="px-8 py-2 text-right align-top whitespace-nowrap">
          <RunNow name={asset.name} label={label.name} />
          <button
            type="button"
            aria-expanded={open}
            aria-label={`Data flow for ${label.name}`}
            onClick={() => setOpen((o) => !o)}
            className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-[13px] font-semibold text-blue-ink hover:underline"
          >
            Data flow
            <ChevronRight
              className={cn("size-3.5 transition-transform duration-[160ms]", open && "rotate-90")}
              aria-hidden
            />
          </button>
        </td>
      </tr>
      {open && (
        <tr className="border-b border-hair bg-surface-2" data-testid="lineage-row">
          <td colSpan={5} className="px-8 py-3">
            <dl className="m-0 grid grid-cols-[auto_1fr] items-baseline gap-x-3 gap-y-1.5 text-[13px]">
              <dt className="text-muted">Comes from</dt>
              <dd className="m-0">
                <Chips ids={asset.upstream} none="None (original source)" />
              </dd>
              <dt className="text-muted">Used by</dt>
              <dd className="m-0">
                <Chips ids={asset.downstream} none="None (end result)" />
              </dd>
              <dt className="text-muted">Max age</dt>
              <dd className="m-0 tnum">
                {asset.freshness_limit_s === null ? "No limit" : ageText(asset.freshness_limit_s)}
              </dd>
            </dl>
          </td>
        </tr>
      )}
    </>
  );
}

function RecentLoads() {
  const runs = usePipelineRuns();
  const skipped = new Set(
    (useAssets().data ?? []).flatMap((a) => (a.last_run?.skipped ? [a.last_run.run_id] : [])),
  );
  const [open, setOpen] = useState(false);
  const total = runs.data?.length ?? 0;
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="border-b border-hair">
      <CollapsibleTrigger className="flex h-11 w-full items-center gap-1.5 px-8 text-[13px] font-semibold text-blue-ink hover:underline">
        <ChevronRight
          className={cn("size-3.5 transition-transform duration-[160ms]", open && "rotate-90")}
          aria-hidden
        />
        Recent data loads{runs.data ? ` (${total})` : ""}
      </CollapsibleTrigger>
      <CollapsibleContent>
        {runs.isPending ? (
          <Loading what="recent data loads" />
        ) : runs.error ? (
          <Failed what="Recent data loads" error={runs.error} />
        ) : total === 0 ? (
          <p className="m-0 px-8 pb-3 text-[13px] text-muted">No data loads yet.</p>
        ) : (
          <table className="w-full border-collapse text-[14px]">
            <caption className="sr-only">Recent data loads</caption>
            <thead>
              <tr>
                <th className={cn(TH, "px-8")}>Dataset</th>
                <th className={TH}>Result</th>
                <th className={TH}>Ran at (real time)</th>
                <th className={cn(TH, "text-right")}>Duration</th>
                <th className={cn(TH, "px-8 text-right")}>Rows in / kept</th>
              </tr>
            </thead>
            <tbody>
              {runs.data.map((r) => (
                <tr key={r.run_id} className="h-11 border-b border-hair">
                  <td className="px-8" title={r.asset}>
                    {assetLabel(r.asset).name}
                  </td>
                  <td className="px-3">
                    {skipped.has(r.run_id) ? (
                      <span className="text-muted">Not run</span>
                    ) : (
                      <Mark tone={RUN_TONE[r.status].tone}>{RUN_TONE[r.status].label}</Mark>
                    )}
                  </td>
                  <td className="px-3 tnum" title={PLATFORM_CLOCK}>
                    {platformTime(r.started_at)}
                  </td>
                  <td className="px-3 text-right tnum">{tookText(r.started_at, r.finished_at)}</td>
                  <td className="px-8 text-right tnum">
                    {r.rows_in.toLocaleString("en-US")} / {r.rows_out.toLocaleString("en-US")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

function Datasets() {
  const assets = useAssets();
  if (assets.isPending) return <Loading what="datasets" />;
  if (assets.error) return <Failed what="Datasets" error={assets.error} />;
  if (assets.data.length === 0)
    return <EmptyState icon={Database} title="No datasets yet." className="py-6" />;
  return (
    <>
      <table className="w-full border-collapse text-[14px]">
        <caption className="sr-only">Datasets</caption>
        <thead>
          <tr>
            <th className={cn(TH, "px-8")}>Dataset</th>
            <th className={TH}>Last load</th>
            <th className={TH}>Rows stored</th>
            <th className={TH}>Data checks</th>
            <th className={cn(TH, "px-8 text-right")}>Detail</th>
          </tr>
        </thead>
        <tbody>
          {assets.data.map((a) => (
            <AssetRow key={a.name} asset={a} />
          ))}
        </tbody>
      </table>
      <RecentLoads />
    </>
  );
}

const FRESHNESS = "freshness.";

function checkName(name: string, sources: Map<string, string>): string {
  const source = name.startsWith(FRESHNESS) ? sources.get(name.slice(FRESHNESS.length)) : undefined;
  if (source) return `Freshness: ${source}`;
  return name === "ingest.late_arrivals" ? "Late arrivals" : humanize(name);
}

function observedText(observed: string): string {
  const age = /^product age (\d+) s$/.exec(observed);
  if (age) return `Data age ${ageText(Number(age[1]))}`;
  const lag = /^ingest lag (\d+) s$/.exec(observed);
  if (lag) return `${ageText(Number(lag[1]))} delay`;
  const late = /^(\d+) event\(s\) known later than \d+x freshness$/.exec(observed);
  if (late) return `${plural(Number(late[1]), "reading")} arrived very late`;
  return sentence(observed);
}

function CheckRow({ c, sources }: { c: DqCheck; sources: Map<string, string> }) {
  return (
    <tr className="h-11 border-b border-hair" data-testid="check-row">
      <td className="px-8 py-1">
        <span className="block" title={c.name}>
          {checkName(c.name, sources)}
        </span>
        <span className="text-[12px] text-muted" title={c.asset}>
          {assetLabel(c.asset).name}
        </span>
      </td>
      <td className="px-3">
        {c.passed ? (
          <Mark tone="ok">Passed</Mark>
        ) : (
          <Mark tone={c.severity === "error" ? "bad" : "warn"}>
            {c.severity === "error" ? "Failed" : "Warning"}
          </Mark>
        )}
      </td>
      <td className="max-w-[260px] truncate px-3 text-muted" title={c.observed}>
        {observedText(c.observed)}
      </td>
      <td className="px-8 text-right tnum">{dayTime(c.checked_at)}</td>
    </tr>
  );
}

function ChecksTable({ rows, label }: { rows: DqCheck[]; label: string }) {
  const feeds = useFeeds();
  const sources = new Map((feeds.data ?? []).map((f) => [f.source_id, feedName(f)]));
  return (
    <table className="w-full border-collapse text-[14px]">
      <caption className="sr-only">{label}</caption>
      <thead>
        <tr>
          <th className={cn(TH, "px-8")}>Check</th>
          <th className={TH}>Result</th>
          <th className={TH}>Observed</th>
          <th className={cn(TH, "px-8 text-right")}>Checked at</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <CheckRow key={c.check_id} c={c} sources={sources} />
        ))}
      </tbody>
    </table>
  );
}

function Checks() {
  const checks = useChecks();
  const [open, setOpen] = useState(false);
  const rows = checks.data ?? [];
  const problems = rows
    .filter((c) => !c.passed)
    .sort((a, b) => Number(b.severity === "error") - Number(a.severity === "error"));
  const passed = rows.filter((c) => c.passed);
  const failedCount = problems.filter((c) => c.severity === "error").length;
  if (checks.isPending) return <Loading what="data checks" />;
  if (checks.error) return <Failed what="Data checks" error={checks.error} />;
  if (rows.length === 0) return <EmptyState icon={Database} title="No data checks yet." className="py-6" />;
  return (
    <>
      <p className="m-0 px-8 pb-3 text-[13px] text-muted" data-testid="checks-summary">
        {plural(rows.length, "check")}: {passed.length} passed
        {failedCount > 0 && `, ${failedCount} failed`}
        {problems.length > failedCount && `, ${plural(problems.length - failedCount, "warning")}`}
      </p>
      {problems.length > 0 && <ChecksTable rows={problems} label="Failed checks" />}
      {passed.length > 0 && (
        <Collapsible open={open} onOpenChange={setOpen} className="border-b border-hair">
          <CollapsibleTrigger className="flex h-11 w-full items-center gap-1.5 px-8 text-[13px] font-semibold text-blue-ink hover:underline">
            <ChevronRight
              className={cn("size-3.5 transition-transform duration-[160ms]", open && "rotate-90")}
              aria-hidden
            />
            Passed checks ({passed.length})
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ChecksTable rows={passed} label="Checks that passed" />
          </CollapsibleContent>
        </Collapsible>
      )}
    </>
  );
}

/** The mockup's folded "Pipeline" row: datasets, data loads and data checks open one click deeper, and open by themselves when something failed. */
function DatasetsGroup() {
  const assets = useAssets();
  const checks = useChecks();
  const loadedAssets = assets.data ?? [];
  const done = loadedAssets.filter((a) => a.last_run?.status === "success" && !a.last_run.skipped).length;
  const problem =
    loadedAssets.some((a) => a.last_run && a.last_run.status !== "success") ||
    (checks.data ?? []).some((c) => !c.passed);
  const [toggled, setToggled] = useState<boolean | null>(null);
  const open = toggled ?? problem;
  const passed = (checks.data ?? []).filter((c) => c.passed).length;
  return (
    <section aria-label="Datasets and checks">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setToggled(!open)}
        className="flex h-11 w-full items-center gap-2 border-b border-hair bg-surface-2 px-8 text-left text-[13px]"
      >
        <ChevronRight
          className={cn("size-4 text-muted transition-transform duration-[160ms]", open && "rotate-90")}
          aria-hidden
        />
        <span className="font-semibold text-ink-2">Datasets</span>
        {assets.data && checks.data && (
          <span className="text-muted">
            {done} {done === 1 ? "load" : "loads"} done, {passed} checks passed
          </span>
        )}
        {problem && <CountBadge count="needs attention" tone="warn" />}
      </button>
      {open && (
        <>
          <SectionHead title="Datasets" info="pipeline_run" />
          <Datasets />
          <SectionHead title="Data checks" info="dq_check" />
          <Checks />
        </>
      )}
    </section>
  );
}

export function DataTab() {
  const scripted = isPack(useScenario().data?.scenario);
  return (
    <div>
      {scripted ? (
        <StatusLine
          tone="idle"
          headline="No live feeds in this exercise."
          detail="Hurricane Ian runs on scripted exercise data (synthetic); data feeds replay for Helene only."
        />
      ) : (
        <>
          <Summary />
          <FeedsTable />
        </>
      )}
      <DatasetsGroup />
    </div>
  );
}
