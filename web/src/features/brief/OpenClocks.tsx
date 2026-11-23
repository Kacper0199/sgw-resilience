import { ClipboardCheck } from "lucide-react";
import { FUNCTION_LABEL } from "@/auth/personas";
import { CountBadge, type DataColumn, DataTable, EmptyState, Section, Tag } from "@/components/sgw";
import { cn } from "@/lib/cn";
import { formatETOn, formatRelative, urgencyOf } from "@/lib/time";
import { ViewDecision } from "../agent-panel/decisionLink";
import { actionMark, decisionTitle } from "../decisions/actionTypes";
import { useCard } from "../decisions/useQueue";
import type { BriefClock } from "./types";

const waitingNames = (c: BriefClock) =>
  c.waiting_for.length > 0 ? c.waiting_for.map((f) => FUNCTION_LABEL[f]).join(", ") : "All signed";

function DecisionCell({ c }: { c: BriefClock }) {
  const card = useCard(c.proposal_id).data;
  const mark = card ? actionMark(card.action_type, card.params) : undefined;
  return (
    <div className="min-w-0">
      <div className="flex items-start gap-1.5 text-[14px] leading-5 font-semibold">
        {mark && <mark.Icon className="mt-[3px] size-3.5 shrink-0 text-muted" aria-hidden />}
        <span>
          {mark && <span className="sr-only">{mark.label}: </span>}
          {decisionTitle(c.title)}
        </span>
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
        {card && (
          <Tag domain={card.case.domain === "water" ? "water" : "power"}>
            {card.case.domain === "water" ? "Water" : "Power"}
          </Tag>
        )}
      </div>
      <div className="mt-1 text-[13px] text-muted min-[820px]:hidden">Waiting for {waitingNames(c)}</div>
      <ViewDecision id={c.proposal_id} className="mt-1 min-[820px]:hidden" />
    </div>
  );
}

const TONE = { normal: "text-ink", soon: "text-warn", missed: "text-crit" } as const;

function columns(now: string): DataColumn<BriefClock>[] {
  return [
    {
      id: "deadline",
      header: "Deadline",
      className: "w-36 whitespace-nowrap max-[819px]:w-24",
      cell: (c) => (
        <span className="flex flex-col leading-tight tnum">
          <b className="text-[14px]">{formatETOn(c.effective_decide_by_utc, now)}</b>
          <span className={cn("font-mono text-[12px]", TONE[urgencyOf(c.effective_decide_by_utc, now)])}>
            {formatRelative(c.effective_decide_by_utc, now)}
          </span>
        </span>
      ),
    },
    { id: "decision", header: "Decision", cell: (c) => <DecisionCell c={c} /> },
    {
      id: "waiting",
      header: "Waiting for",
      className: "w-48 text-[13px] max-[819px]:hidden",
      headerClassName: "max-[819px]:hidden",
      cell: waitingNames,
    },
    {
      id: "view",
      header: <span className="sr-only">Open</span>,
      align: "end",
      className: "w-36 max-[819px]:hidden",
      headerClassName: "max-[819px]:hidden",
      cell: (c) => <ViewDecision id={c.proposal_id} />,
    },
  ];
}

export function OpenClocks({ clocks, now }: { clocks: BriefClock[]; now: string }) {
  return (
    <Section
      title={
        <>
          Decisions needing two teams
          {clocks.length > 0 && <CountBadge count={clocks.length} />}
        </>
      }
      info="tier_T3"
    >
      {clocks.length === 0 ? (
        <EmptyState icon={ClipboardCheck} title="No decisions are waiting for two teams." />
      ) : (
        <DataTable
          data={clocks}
          columns={columns(now)}
          getRowId={(c) => c.proposal_id}
          caption="Decisions needing two teams, by deadline"
          rowTestId="open-clock"
          className="[&_td:first-child]:pl-0 [&_td:last-child]:pr-0 [&_th:first-child]:pl-0 [&_th:last-child]:pr-0"
        />
      )}
    </Section>
  );
}
