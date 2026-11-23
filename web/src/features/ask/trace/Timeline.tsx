import { Check, X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { cost, count, ms } from "./format";
import { MODE_LABEL, shortModel } from "./labels";
import type { CheckRow, Lane, LlmCall, Outcome, Phase, ToolRow } from "./model";

const GRID = "grid grid-cols-[minmax(0,1fr)_104px_52px_48px] items-baseline gap-x-2";
const NUM = "text-right text-[12px] tnum";

function OutcomeIcon({ outcome }: { outcome: Outcome | "pass" | "fail" }) {
  const Icon = outcome === "ok" || outcome === "pass" ? Check : X;
  const tone =
    outcome === "refused"
      ? "text-warn"
      : outcome === "error" || outcome === "fail"
        ? "text-crit"
        : "text-muted";
  return <Icon aria-hidden className={cn("mt-[3px] size-3 shrink-0 self-start", tone)} strokeWidth={2} />;
}

function ToolLine({ tool }: { tool: ToolRow }) {
  return (
    <li className={cn(GRID, "py-1")} data-testid="trace-tool" data-outcome={tool.outcome}>
      <span className="col-span-3 flex min-w-0 items-baseline gap-1.5 text-[13px]">
        <OutcomeIcon outcome={tool.outcome} />
        <span className="min-w-0 truncate">
          {tool.verb}
          {tool.arg && <span className="ml-1.5 font-mono text-[12px] text-muted">{tool.arg}</span>}
          {tool.tag && <span className="ml-1.5 text-[12px] text-muted">{tool.tag}</span>}
          {tool.outcome !== "ok" && (
            <span
              className={cn(
                "ml-1.5 text-[12px] font-medium",
                tool.outcome === "refused" ? "text-warn" : "text-crit",
              )}
            >
              {tool.outcome === "refused" ? "Refused" : "Failed"}
            </span>
          )}
        </span>
      </span>
      <span className={cn(NUM, "text-muted")}>{ms(tool.ms)}</span>
    </li>
  );
}

function LlmLine({ call }: { call: LlmCall }) {
  const note = [
    call.mode ? MODE_LABEL[call.mode] : null,
    call.cacheRead > 0 ? `${count(call.cacheRead)} cached` : null,
  ]
    .filter(Boolean)
    .join(", ");
  return (
    <li className={cn(GRID, "py-1")} data-testid="trace-llm">
      <span className="min-w-0 text-[13px]">
        <span className="block truncate font-medium">{call.model ? shortModel(call.model) : "AI step"}</span>
        {note && <span className="block text-[12px] leading-4 text-muted">{note}</span>}
      </span>
      <span className={NUM}>
        {count(call.tokensIn)} / {count(call.tokensOut)}
      </span>
      <span className={cn(NUM, call.costMicros === 0 && "text-muted")}>{cost(call.costMicros)}</span>
      <span className={NUM}>{ms(call.ms)}</span>
    </li>
  );
}

function CheckLine({ check }: { check: CheckRow }) {
  return (
    <li
      className="flex items-baseline gap-1.5 py-1 text-[13px]"
      data-testid="trace-check"
      data-passed={check.passed}
    >
      <OutcomeIcon outcome={check.passed ? "pass" : "fail"} />
      <span className="min-w-0 flex-1 truncate">{check.label}</span>
      <span className={cn("text-[12px] font-medium", check.passed ? "text-muted" : "text-crit")}>
        {check.passed ? "Passed" : "Failed"}
      </span>
    </li>
  );
}

function LaneBlock({ lane, longest }: { lane: Lane; longest: number }) {
  const width = lane.ms !== null && longest > 0 ? Math.max(4, Math.round((lane.ms / longest) * 100)) : 0;
  return (
    <li className="border-l-2 border-blue-line pl-3" data-testid="trace-lane" data-worker={lane.worker}>
      <div className={GRID}>
        <h4 className="m-0 min-w-0 truncate text-[13px] font-semibold">
          {lane.label}
          {lane.fallback && (
            <span className="ml-1.5 text-[12px] font-normal text-warn">Answered by code</span>
          )}
        </h4>
        <span />
        <span />
        <span className={cn(NUM, "font-medium")}>{ms(lane.ms)}</span>
      </div>
      <div aria-hidden className="mt-1 h-[3px] rounded-full bg-surface-3">
        <div className="h-full rounded-full bg-blue" style={{ width: `${width}%` }} />
      </div>
      <ul className="m-0 mt-1 list-none p-0">
        {lane.tools.map((t) => (
          <ToolLine key={t.seq} tool={t} />
        ))}
        {lane.llm.map((l) => (
          <LlmLine key={l.seq} call={l} />
        ))}
      </ul>
    </li>
  );
}

function PhaseBody({ phase }: { phase: Phase }): ReactNode {
  const longest = Math.max(0, ...phase.lanes.map((l) => l.ms ?? 0));
  return (
    <>
      {phase.lanes.length > 0 && (
        <ul className="m-0 mt-1.5 flex list-none flex-col gap-3 p-0">
          {phase.lanes.map((l) => (
            <LaneBlock key={l.worker} lane={l} longest={longest} />
          ))}
        </ul>
      )}
      {(phase.tools.length > 0 || phase.llm.length > 0) && (
        <ul className="m-0 mt-0.5 list-none p-0">
          {phase.tools.map((t) => (
            <ToolLine key={t.seq} tool={t} />
          ))}
          {phase.llm.map((l) => (
            <LlmLine key={l.seq} call={l} />
          ))}
        </ul>
      )}
      {phase.checks.length > 0 && (
        <ul className="m-0 mt-0.5 list-none p-0">
          {phase.checks.map((c) => (
            <CheckLine key={c.seq} check={c} />
          ))}
        </ul>
      )}
    </>
  );
}

const failed = (p: Phase) => p.checks.some((c) => !c.passed) || p.lanes.some((l) => l.outcome === "error");

/** The graph as a vertical timeline: one dot per phase, the specialists side by side as lanes, tool calls under their lane. */
export function Timeline({ phases }: { phases: Phase[] }) {
  return (
    <ol aria-label="Steps" className="m-0 list-none p-0" data-testid="trace-timeline">
      {phases.map((p, i) => (
        <li key={p.id} className="relative pb-4 pl-6 last:pb-0" data-testid="trace-phase" data-phase={p.id}>
          {i < phases.length - 1 && (
            <span aria-hidden className="absolute top-[18px] bottom-0 left-[4px] w-px bg-hair-strong" />
          )}
          <span
            aria-hidden
            className={cn(
              "absolute top-[7px] left-0 size-[9px] rounded-full",
              failed(p) ? "bg-crit" : "bg-ink-2",
            )}
          />
          <div className={GRID}>
            <h3 className="m-0 text-[14px] leading-6 font-semibold">
              {p.label}
              {p.lanes.length > 1 && (
                <span className="ml-2 text-[12px] font-normal text-muted">in parallel</span>
              )}
            </h3>
            <span />
            <span />
            <span className={cn(NUM, "font-medium")}>{p.ms === null ? "" : ms(p.ms)}</span>
          </div>
          <PhaseBody phase={p} />
        </li>
      ))}
    </ol>
  );
}
