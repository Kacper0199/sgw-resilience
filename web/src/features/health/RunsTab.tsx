import { Bot, ExternalLink } from "lucide-react";
import { Fragment, useState } from "react";
import { EmptyState } from "@/components/sgw";
import { cn } from "@/lib/cn";
import { TraceSheet, useCanSeeTrace, useOpenTrace } from "../ask/trace";
import { Failed, Loading } from "./Async";
import { CancelRun } from "./CancelRun";
import {
  durationMs,
  graphName,
  humanize,
  modelName,
  PLATFORM_CLOCK,
  platformTime,
  plural,
  tokens,
  usd,
  usdMicros,
} from "./format";
import { SectionHead } from "./SectionHead";
import { Mark, StatusLine, type Tone } from "./Status";
import { TH } from "./tables";
import type { AgentRun, RunStatus } from "./types";
import { isNotShown, useAgentRun, useAgentRuns, useUsage } from "./useHealth";

const STATUS: Record<RunStatus, { tone: Tone; label: string }> = {
  completed: { tone: "ok", label: "Done" },
  running: { tone: "idle", label: "Running" },
  waiting_approval: { tone: "warn", label: "Waiting for sign-off" },
  failed: { tone: "bad", label: "Failed" },
  cancelled: { tone: "idle", label: "Stopped" },
};

const STEP_TONE = { ok: "ok", failed: "bad", denied: "warn", skipped: "idle" } as const;
const STEP_LABEL = { ok: "Done", failed: "Failed", denied: "Not allowed", skipped: "Skipped" } as const;
const KIND_LABEL = { llm_call: "AI step", graph_step: "Step" } as const;

const cost = (r: Pick<AgentRun, "billed" | "cost_usd_micros" | "run_mode">) =>
  r.cost_usd_micros === null
    ? "–"
    : r.billed
      ? usdMicros(r.cost_usd_micros)
      : r.run_mode === "replay"
        ? "Replay, no cost"
        : "No cost";

function Summary() {
  const runs = useAgentRuns();
  const usage = useUsage();
  if (runs.isPending)
    return <StatusLine tone="idle" headline="Loading AI activity…" detail="Recent requests are loading." />;
  if (isNotShown(runs.error)) return <StatusLine tone="idle" headline="AI activity isn't available yet." />;
  if (runs.error)
    return <StatusLine tone="bad" headline="Couldn't load AI activity." detail="Try again in a moment." />;
  const money = usage.data ? ` ${usd(usage.data.total.cost_usd)} spent so far.` : "";
  if (runs.data.length === 0)
    return (
      <StatusLine
        tone="idle"
        headline="No AI activity yet."
        detail="Requests appear after the first question or situation report."
      />
    );
  const failed = runs.data.filter((r) => r.status === "failed").length;
  const waiting = runs.data.filter((r) => r.status === "waiting_approval").length;
  if (failed > 0)
    return (
      <StatusLine
        tone="warn"
        headline={`${failed} of ${runs.data.length} recent requests failed.`}
        detail={`Open its steps to see where it stopped.${money}`}
      />
    );
  return (
    <StatusLine
      tone="ok"
      headline={`${runs.data.length} recent requests, none failed.`}
      detail={`${waiting ? `${waiting} waiting for sign-off.` : "Nothing is waiting."}${money}`}
    />
  );
}

function Usage() {
  const usage = useUsage();
  return (
    <>
      <SectionHead title="Cost by model" className="pt-6" />
      {!usage.allowed || isNotShown(usage.error) ? (
        <p className="m-0 px-8 pb-4 text-[13px] text-muted" data-testid="usage-hidden">
          Only platform, command and executive roles can see costs.
        </p>
      ) : usage.isPending ? (
        <Loading what="usage" />
      ) : usage.error ? (
        <Failed what="Usage" error={usage.error} />
      ) : usage.data.rows.length === 0 ? (
        <p className="m-0 px-8 pb-4 text-[13px] text-muted">No AI usage yet.</p>
      ) : (
        <table className="w-full border-collapse text-[14px]">
          <caption className="sr-only">Usage by model</caption>
          <thead>
            <tr>
              <th className={cn(TH, "px-8")}>Model</th>
              <th className={cn(TH, "text-right")}>Requests</th>
              <th className={cn(TH, "text-right")}>AI text in / out (tokens)</th>
              <th className={cn(TH, "text-right")}>Cost</th>
              <th className={cn(TH, "text-right")}>Typical wait</th>
              <th className={cn(TH, "px-8 text-right")}>95% done within</th>
            </tr>
          </thead>
          <tbody>
            {usage.data.rows.map((r) => (
              <tr key={String(r.model)} className="h-11 border-b border-hair" data-testid="usage-row">
                <td className="px-8 font-medium">{modelName(String(r.model))}</td>
                <td className="px-3 text-right tnum">{r.calls}</td>
                <td className="px-3 text-right tnum">
                  {tokens(r.input_tokens)} / {tokens(r.output_tokens)}
                </td>
                <td className="px-3 text-right tnum">
                  {r.billed_calls === 0 ? <span className="text-muted">No cost</span> : usd(r.cost_usd)}
                </td>
                <td className="px-3 text-right tnum">{durationMs(r.latency_p50_ms)}</td>
                <td className="px-8 text-right tnum">{durationMs(r.latency_p95_ms)}</td>
              </tr>
            ))}
            <tr className="h-11 border-b border-hair bg-surface-2" data-testid="usage-total">
              <td className="px-8 font-semibold">All models</td>
              <td className="px-3 text-right font-semibold tnum">{usage.data.total.calls}</td>
              <td className="px-3 text-right font-semibold tnum">
                {tokens(usage.data.total.input_tokens)} / {tokens(usage.data.total.output_tokens)}
              </td>
              <td className="px-3 text-right font-semibold tnum">{usd(usage.data.total.cost_usd)}</td>
              <td className="px-3 text-right tnum">{durationMs(usage.data.total.latency_p50_ms)}</td>
              <td className="px-8 text-right tnum">{durationMs(usage.data.total.latency_p95_ms)}</td>
            </tr>
          </tbody>
        </table>
      )}
    </>
  );
}

function Trace({ run }: { run: AgentRun }) {
  const detail = useAgentRun(run.run_id);
  return (
    <tr className="border-b border-hair bg-surface-2" data-testid="trace-row">
      <td colSpan={7} className="px-8 py-3">
        {detail.isPending ? (
          <Loading what="steps" />
        ) : detail.error ? (
          <Failed what="The steps" error={detail.error} />
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-3">
              <p className="m-0 text-[13px] text-muted">
                {plural(detail.data.steps.length, "step")}, {plural(run.llm_calls, "AI step")}
                {run.error_code ? `, stopped: ${humanize(run.error_code).toLowerCase()}` : ""}
              </p>
              {run.trace_url && (
                <a
                  href={run.trace_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[13px] font-semibold text-blue-ink hover:underline"
                >
                  Open run details (MLflow)
                  <ExternalLink className="size-3.5" aria-hidden />
                </a>
              )}
            </div>
            <table className="w-full border-collapse text-[13px]">
              <caption className="sr-only">{`Steps of request ${run.run_id}`}</caption>
              <thead>
                <tr className="h-8 text-left text-[12px] font-semibold text-muted">
                  <th className="w-8 pr-3 pl-0 font-semibold">#</th>
                  <th className="px-3 font-semibold">Step</th>
                  <th className="px-3 font-semibold">Result</th>
                  <th className="px-3 text-right font-semibold">Duration</th>
                  <th className="px-3 text-right font-semibold">AI text in / out (tokens)</th>
                  <th className="pr-0 pl-3 text-right font-semibold">Cost</th>
                </tr>
              </thead>
              <tbody>
                {detail.data.steps.map((s) => (
                  <tr key={s.seq} className="h-9 border-t border-hair" data-testid="trace-step">
                    <td className="pr-3 pl-0 text-muted tnum">{s.seq}</td>
                    <td className="px-3">
                      <span className="text-muted">{KIND_LABEL[s.kind]}: </span>
                      <span className="font-mono text-[12px]">{s.name}</span>
                    </td>
                    <td className="px-3">
                      <Mark tone={STEP_TONE[s.status]}>{STEP_LABEL[s.status]}</Mark>
                    </td>
                    <td className="px-3 text-right tnum">{durationMs(s.duration_ms)}</td>
                    <td className="px-3 text-right tnum">
                      {s.input_tokens === null
                        ? "–"
                        : `${tokens(s.input_tokens)} / ${tokens(s.output_tokens ?? 0)}`}
                    </td>
                    <td className="pr-0 pl-3 text-right tnum">
                      {s.cost_usd_micros === null || !run.billed ? "–" : usdMicros(s.cost_usd_micros)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </td>
    </tr>
  );
}

function Requests() {
  const runs = useAgentRuns();
  const [open, setOpen] = useState<string | null>(null);
  const openTrace = useOpenTrace();
  return (
    <>
      <SectionHead title="Recent requests" info="ai_run" />
      {runs.isPending ? (
        <Loading what="requests" />
      ) : isNotShown(runs.error) ? (
        <EmptyState icon={Bot} title="AI activity isn't available yet." className="py-6" />
      ) : runs.error ? (
        <Failed what="Requests" error={runs.error} />
      ) : runs.data.length === 0 ? (
        <EmptyState icon={Bot} title="No AI requests yet." className="py-6" />
      ) : (
        <table className="w-full border-collapse text-[14px]">
          <caption className="sr-only">Recent AI requests</caption>
          <thead>
            <tr>
              <th className={cn(TH, "px-8")}>Request</th>
              <th className={TH}>Result</th>
              <th className={TH}>Ran at (real time)</th>
              <th className={cn(TH, "text-right")}>Duration</th>
              <th className={cn(TH, "text-right")}>AI text in / out (tokens)</th>
              <th className={cn(TH, "text-right")}>Cost</th>
              <th className={cn(TH, "px-8 text-right")}>Steps</th>
            </tr>
          </thead>
          <tbody>
            {runs.data.map((r) => {
              const expanded = open === r.run_id;
              return (
                <Fragment key={r.run_id}>
                  <tr className="border-b border-hair" data-testid="agent-run-row">
                    <td className="px-8 py-2 align-top">
                      <span className="block font-medium">
                        {r.node ? humanize(r.node) : graphName(r.graph)}
                      </span>
                      <span className="block text-[12px] text-muted" title={r.run_id}>
                        {graphName(r.graph)}
                      </span>
                    </td>
                    <td className="px-3 py-2 align-top">
                      <Mark tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Mark>
                      {r.error_code && (
                        <span className="block text-[12px] text-muted">{humanize(r.error_code)}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 align-top tnum" title={PLATFORM_CLOCK}>
                      {platformTime(r.started_at)}
                    </td>
                    <td className="px-3 py-2 text-right align-top tnum">{durationMs(r.duration_ms)}</td>
                    <td className="px-3 py-2 text-right align-top tnum">
                      {tokens(r.input_tokens)} / {tokens(r.output_tokens)}
                    </td>
                    <td className={cn("px-3 py-2 text-right align-top tnum", !r.billed && "text-muted")}>
                      {cost(r)}
                    </td>
                    <td className="px-8 py-2 text-right align-top">
                      {openTrace ? (
                        <button
                          type="button"
                          aria-label={`How request ${r.run_id} was made`}
                          onClick={() => openTrace(r.run_id)}
                          className="inline-flex h-7 items-center text-[13px] font-semibold text-blue-ink hover:underline"
                        >
                          How it was made
                        </button>
                      ) : (
                        <button
                          type="button"
                          aria-expanded={expanded}
                          aria-label={`${expanded ? "Hide" : "Show"} steps for request ${r.run_id}`}
                          onClick={() => setOpen(expanded ? null : r.run_id)}
                          className="inline-flex h-7 items-center text-[13px] font-semibold text-blue-ink hover:underline"
                        >
                          {expanded ? "Hide steps" : "Show steps"}
                        </button>
                      )}
                      <CancelRun run={r} />
                    </td>
                  </tr>
                  {expanded && <Trace run={r} />}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
    </>
  );
}

export function RunsTab() {
  const canTrace = useCanSeeTrace();
  return (
    <div>
      {canTrace && <TraceSheet />}
      <Summary />
      <Usage />
      <Requests />
    </div>
  );
}
