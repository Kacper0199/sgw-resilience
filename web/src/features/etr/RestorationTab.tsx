import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Clock } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import {
  type DataColumn,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  Section,
  SourceLine,
} from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { decisionHref } from "@/lib/links";
import { usePhase } from "@/lib/PhaseProvider";
import { formatRelative } from "@/lib/time";
import { personaTitle } from "../after-action/format";
import { etrApi } from "./api";
import {
  axis,
  count,
  earliest,
  functionList,
  latest,
  p50Status,
  percent,
  stillOutText,
  when,
} from "./format";
import type { EtrArea, EtrPublication, EtrView } from "./types";
import { ETR_KEY, useEtr } from "./useEtr";

function RangeBar({ a, at }: { a: EtrArea; at: (iso: string) => number }) {
  const left = at(a.p10_utc);
  const width = Math.max(at(a.p90_utc) - left, 1);
  return (
    <div
      role="img"
      aria-label={`80% range ${when(a.p10_utc)} to ${when(a.p90_utc)}, middle ${when(a.p50_utc)}`}
      className="relative h-3 w-full min-w-[120px] bg-[var(--chart-track)]"
    >
      <span
        className="absolute inset-y-0 bg-[var(--chart-band-mid)]"
        style={{ left: `${left}%`, width: `${width}%` }}
      />
      <span
        className="absolute -inset-y-0.5 w-0.5 bg-[var(--chart-median)] dark:bg-ink"
        style={{ left: `calc(${at(a.p50_utc)}% - 1px)` }}
      />
    </div>
  );
}

function Stat({
  label,
  value,
  line,
  testId,
}: {
  label: string;
  value: string;
  line?: string;
  testId?: string;
}) {
  return (
    <div className="min-w-0 border-l border-divider pl-4 first:border-l-0 first:pl-0" data-testid={testId}>
      <dt className="text-[12px] font-semibold text-muted">{label}</dt>
      <dd className="m-0 text-[20px] leading-7 font-semibold tnum">{value}</dd>
      {line && <dd className="m-0 text-[12px] text-muted tnum">{line}</dd>}
    </div>
  );
}

function DecisionLink({ id }: { id: string }) {
  return (
    <Link
      to={decisionHref(id)}
      className="inline-flex items-center text-[13px] font-semibold text-blue-ink hover:underline"
    >
      View decision
      <ChevronRight className="size-3.5" aria-hidden />
    </Link>
  );
}

const CLOSED = new Set(["expired", "rejected", "withdrawn"]);

const STOPPED = new Set(["error", "cancelled"]);

function statusLine(pub: EtrPublication, canPublish: boolean): string {
  if (pub.state !== "executed" && STOPPED.has(pub.run_status ?? ""))
    return "The last draft stopped before it was published.";
  const missing = pub.required_functions.filter((f) => !pub.signed_functions.includes(f));
  if (pub.state === "executed" && pub.published_at)
    return `Published ${when(pub.published_at)} by ${personaTitle(pub.published_by ?? pub.proposed_by)}.`;
  if (pub.state === "approved")
    return canPublish
      ? "Signed. Ready to publish."
      : `Signed. ${personaTitle(pub.proposed_by)} publishes it.`;
  if (CLOSED.has(pub.state)) return `Last draft ${pub.state.replace("_", " ")}.`;
  return missing.length === pub.required_functions.length
    ? `Waiting for ${functionList(missing)} to sign.`
    : `Waiting for ${functionList(missing)} to sign. ${functionList(pub.signed_functions)} signed.`;
}

function Publication({
  view,
  onDraft,
  onPublish,
  busy,
}: {
  view: EtrView;
  onDraft: () => void;
  onPublish: () => void;
  busy: boolean;
}) {
  const pub = view.publication;
  if (view.drafting) return <p className="m-0 text-[14px] font-semibold">Drafting the global ETR…</p>;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2" data-testid="etr-publication">
      {pub ? (
        <p className="m-0 text-[14px]">{statusLine(pub, view.can_publish)}</p>
      ) : (
        <p className="m-0 text-[14px] text-muted">Not published yet.</p>
      )}
      {pub && !CLOSED.has(pub.state) && <DecisionLink id={pub.proposal_id} />}
      {view.can_publish && (
        <Button variant="primary" size="sm" onClick={onPublish} disabled={busy}>
          {busy ? "Publishing…" : "Publish"}
        </Button>
      )}
      {view.can_draft && (
        <Button variant="primary" size="sm" onClick={onDraft} disabled={busy}>
          {pub?.state === "executed" ? "Revise global ETR" : "Draft global ETR"}
        </Button>
      )}
      {pub?.state === "executed" && view.revision?.due && (
        <p className="m-0 basis-full text-[14px] text-warn" data-testid="etr-revision">
          {view.revision.reason}{" "}
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="underline decoration-dotted underline-offset-2">
                ({view.revision.rule_name ?? "ETR revision rule"})
              </span>
            </TooltipTrigger>
            <TooltipContent>{view.revision.rule}</TooltipContent>
          </Tooltip>
        </p>
      )}
      {pub?.state === "executed" && !view.can_draft && !view.revision?.due && (
        <p className="m-0 basis-full text-[13px] text-muted" data-testid="etr-next">
          {view.revision?.reason ?? "A revision opens when actual restoration moves away from this estimate."}
        </p>
      )}
    </div>
  );
}

const outNow = (a: EtrArea): number => a.actual_out_now ?? a.customers_out_now;
const stillOut = (a: EtrArea): number => a.actual_still_out_ppm ?? a.still_out_ppm;
const stillOutOf = (a: EtrArea): string =>
  stillOutText({ ppm: stillOut(a), restored: Boolean(a.restored_utc && a.outcome?.startsWith("restored")) });

function columns(at: (iso: string) => number, now: string, actual: boolean): DataColumn<EtrArea>[] {
  return [
    {
      id: "area",
      header: "Area",
      cell: (a) => <span className="font-medium">{a.name}</span>,
      sort: (x, y) => x.name.localeCompare(y.name),
    },
    {
      id: "out",
      header: actual ? "Out now" : "Out at estimate",
      align: "end",
      className: "tnum",
      cell: (a) => count(outNow(a)),
      sort: (x, y) => outNow(x) - outNow(y),
    },
    {
      id: "left",
      header: "Still out",
      align: "end",
      className: "tnum",
      cell: (a) => stillOutOf(a),
      sort: (x, y) => stillOut(x) - stillOut(y),
    },
    {
      id: "p50",
      header: "90% restored",
      className: "whitespace-nowrap tnum",
      cell: (a) => (
        <>
          {when(a.p50_utc)}{" "}
          <span className={a.outcome === "late" ? "text-crit" : "text-muted"} data-testid="etr-p50-status">
            {p50Status(a, now)}
          </span>
        </>
      ),
      sort: (x, y) => x.p50_h - y.p50_h,
    },
    {
      id: "p90",
      header: "Latest likely",
      className: "whitespace-nowrap tnum",
      cell: (a) => when(a.p90_utc),
      sort: (x, y) => x.p90_h - y.p90_h,
    },
    {
      id: "range",
      header: "80% range",
      className: "w-[22%]",
      cell: (a) => <RangeBar a={a} at={at} />,
      sort: (x, y) => x.range_h - y.range_h,
    },
  ];
}

export function RestorationTab() {
  const phase = usePhase();
  const qc = useQueryClient();
  const [publishing, setPublishing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const etr = useEtr(publishing);
  const refresh = () => qc.invalidateQueries({ queryKey: ETR_KEY });

  const draft = useMutation({
    mutationFn: etrApi.draft,
    onMutate: () => setProblem(null),
    onSuccess: refresh,
    onError: (err) =>
      setProblem(
        err instanceof ApiError && err.status === 403
          ? "Your role can't draft the ETR."
          : "The draft couldn't start.",
      ),
  });
  const publish = useMutation({
    mutationFn: (runId: string) => etrApi.publish(runId),
    onMutate: () => {
      setProblem(null);
      setPublishing(true);
    },
    onSuccess: refresh,
    onError: () => {
      setPublishing(false);
      setProblem("The ETR couldn't be published. Try again.");
    },
  });

  if (etr.isPending) return <LoadingState rows={6} label="Loading restoration times" className="px-8 pt-4" />;
  if (etr.isError || !etr.data)
    return <ErrorState thing="Restoration times" onRetry={() => void etr.refetch()} className="px-8" />;
  const view = etr.data;
  if (!view.whole)
    return (
      <EmptyState
        icon={Clock}
        title="No restoration estimate yet."
        description={view.next_issue_utc ? `First estimate ${when(view.next_issue_utc)}.` : undefined}
      />
    );
  const whole = view.whole;
  const now = phase.now ?? view.as_of;
  const shown = [whole, ...view.areas];
  const at = axis(earliest(shown.map((a) => a.p10_utc)), latest(shown.map((a) => a.p90_utc)));
  const runId = view.publication?.run_id;
  const revision = view.revision;
  const revised =
    revision?.revised_p50_utc &&
    revision.published_p50_utc &&
    (revision.due || view.publication?.state !== "executed")
      ? { at: revision.revised_p50_utc, published: revision.published_p50_utc }
      : null;
  const inFlight =
    draft.isPending ||
    publish.isPending ||
    (publishing &&
      view.publication?.state !== "executed" &&
      !STOPPED.has(view.publication?.run_status ?? ""));

  return (
    <div data-testid="restoration-tab" className="flex flex-col gap-6 px-8 pt-4">
      <Section title="Whole service area" info="etr">
        <dl
          className={cn(
            "m-0 grid grid-cols-2 gap-y-3",
            revised && view.coverage80_ppm !== null ? "min-[900px]:grid-cols-5" : "min-[900px]:grid-cols-4",
          )}
        >
          <Stat label="90% restored" value={when(whole.p50_utc)} line={p50Status(whole, now)} />
          {revised && (
            <Stat
              testId="etr-revised"
              label="Revised"
              value={when(revised.at)}
              line={`Was ${when(revised.published)}`}
            />
          )}
          <Stat label="Latest likely" value={when(whole.p90_utc)} line={formatRelative(whole.p90_utc, now)} />
          <Stat
            label="Still out"
            value={stillOutOf(whole)}
            line={
              whole.actual_out_now != null
                ? `${count(outNow(whole))} customers now`
                : `${count(whole.customers_out_now)} customers at ${view.issued_at ? when(view.issued_at) : "the estimate"}`
            }
          />
          {view.coverage80_ppm !== null && view.n_storms !== null && (
            <Stat
              label="80% range held"
              value={percent(view.coverage80_ppm)}
              line={`of ${view.n_storms} test storms`}
            />
          )}
        </dl>
        <div className="mt-4">
          <Publication
            view={view}
            busy={inFlight}
            onDraft={() => draft.mutate()}
            onPublish={() => runId && publish.mutate(runId)}
          />
          {problem && (
            <p role="alert" className="m-0 mt-2 text-[14px] text-crit">
              {problem}
            </p>
          )}
        </div>
      </Section>
      <Section title="By area" info="etr_area">
        <div className="overflow-x-auto">
          <DataTable
            compact
            caption="Restoration time by area"
            data={view.areas}
            getRowId={(a) => a.estimate_id}
            columns={columns(at, now, view.actual_as_of != null)}
            rowTestId="etr-row"
          />
        </div>
        <SourceLine>
          {`Issued ${when(view.issued_at ?? view.as_of)}.${
            view.actual_as_of
              ? ` Out now: outage feed at ${when(view.actual_as_of)}, areas by their nearest crew yard.`
              : ""
          } Synthetic data; not yet checked on a real storm.`}
        </SourceLine>
      </Section>
    </div>
  );
}
