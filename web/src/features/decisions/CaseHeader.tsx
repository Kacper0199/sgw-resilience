import { Route } from "lucide-react";
import { forwardRef } from "react";
import { FUNCTION_LABEL } from "@/auth/personas";
import { InfoTip, StatusText, Tag, Tier } from "@/components/sgw";
import type { ProposalCard } from "@/lib/api";
import { usePhase } from "@/lib/PhaseProvider";
import { formatDayTimeET, formatET, formatETOn, formatRelative } from "@/lib/time";
import { ApprovalActions } from "./ApprovalActions";
import { actionMark, decisionTitle } from "./actionTypes";
import { currentShift, describeShift, useClockShifts } from "./clockShifts";
import { EnvelopeChip } from "./Envelope";
import { ShiftChip } from "./ShiftChip";
import { isClosed } from "./severity";
import { signaturesOf } from "./signatures";
import { DOMAIN_LABEL, decisionStatus, timingLineOf, timingOf, timingText } from "./ui";
import { VerdictText } from "./VerdictText";
import { VersionVoidBanner } from "./VersionVoidBanner";
import { WatchRows } from "./WatchRows";
import { WhyTip } from "./WhyBlock";
import { WithdrawAction } from "./WithdrawAction";
import { buildWhy } from "./whyModel";

interface Props {
  card: ProposalCard;
  now: string;
  /** Buttons at the end of the status row (open full page, close). */
  trailing?: React.ReactNode;
}

function Fact({
  label,
  info,
  infoNode,
  value,
  line,
}: {
  label: string;
  info?: Parameters<typeof InfoTip>[0]["term"];
  infoNode?: React.ReactNode;
  value: React.ReactNode;
  line?: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1 text-[12px] font-semibold text-muted">
        {label}
        {info && <InfoTip term={info} />}
        {infoNode}
      </dt>
      <dd className="m-0 text-[15px] leading-5 font-semibold tnum">{value}</dd>
      {line && <dd className="m-0 truncate text-[12px] leading-4 text-muted tnum">{line}</dd>}
    </div>
  );
}

/** Status row, title, version banner, actions and the four key facts; shared by the pane and the full page. */
export const CaseHeader = forwardRef<HTMLHeadingElement, Props>(function CaseHeader(
  { card, now, trailing },
  ref,
) {
  const { shifts } = useClockShifts();
  const status = decisionStatus(card);
  const phase = usePhase();
  const signed = signaturesOf(card);
  const shift = currentShift(shifts, card.decision_case_id, card.effective_decide_by_utc, card.clock_shift);
  const agreement = buildWhy(card).agreement;
  const mark = actionMark(card.action_type, card.params);
  const timingLine = timingLineOf(card, agreement);
  const closed = isClosed(card.state);
  return (
    <div className="flex flex-col gap-3" data-testid="case-header">
      <div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[12px] text-muted">
          <StatusText level={status.level} label={status.label} className="text-[13px]" />
          <Tag domain={card.case.domain === "water" ? "water" : "power"}>
            {DOMAIN_LABEL[card.case.domain]}
          </Tag>
          <Tier tier={card.tier} />
          <span className="inline-flex items-center gap-1" data-testid="action-mark">
            <mark.Icon className="size-3.5" aria-hidden />
            {mark.label}
          </span>
          {card.on_critical_path && (
            <span className="inline-flex items-center gap-1">
              <Route className="size-3" aria-hidden />
              On the critical path
            </span>
          )}
          <EnvelopeChip envelope={card.envelope} />
          <ShiftChip shift={shift} />
          {trailing && <span className="ml-auto flex items-center gap-1">{trailing}</span>}
        </div>
        <h3 ref={ref} tabIndex={-1} className="m-0 mt-2 text-title font-semibold outline-none">
          {decisionTitle(card.title)}
        </h3>
      </div>
      <VersionVoidBanner card={card} />
      <ApprovalActions card={card} now={now} />
      <WithdrawAction card={card} />
      <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-2.5">
        {closed ? (
          <Fact label="Deadline" info="decide_by" value={formatDayTimeET(card.effective_decide_by_utc)} />
        ) : (
          <Fact
            label="Decide by"
            info="decide_by"
            value={formatRelative(card.effective_decide_by_utc, now)}
            line={formatET(card.effective_decide_by_utc)}
          />
        )}
        {shift ? (
          <Fact
            label="Moved at the latest advisory"
            value={describeShift(shift).text.split(", was ")[0]}
            line={`was ${describeShift(shift).text.split("was ")[1]}`}
          />
        ) : (
          <Fact
            label="Impact starts"
            info="consequence"
            value={
              closed
                ? formatDayTimeET(card.case.clock.consequence_utc)
                : formatETOn(card.case.clock.consequence_utc, now)
            }
          />
        )}
        {closed ? (
          <Fact
            label="Signed"
            value={card.decided_at_utc ? formatDayTimeET(card.decided_at_utc) : "Not signed"}
          />
        ) : (
          timingText(timingOf(card), phase) && (
            <Fact
              label="Timing"
              infoNode={<WhyTip card={card} />}
              value={<VerdictText verdict={timingOf(card)} />}
              line={timingLine}
            />
          )
        )}
        <Fact
          label="Signatures"
          info="approval"
          value={`${signed.length} of ${card.functions_required.length}`}
          line={card.functions_required.map((f) => FUNCTION_LABEL[f]).join(", ")}
        />
      </dl>
      <WatchRows card={card} />
    </div>
  );
});
