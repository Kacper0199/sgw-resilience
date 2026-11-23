import { Route } from "lucide-react";
import { Citation, ClockText, EmptyState, InfoTip, LoadingState, TierBadge } from "@/components/sgw";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { actionMark, decisionTitle } from "@/features/decisions/actionTypes";
import type { ProposalCard } from "@/lib/api";
import { cn } from "@/lib/cn";
import { plainIds } from "@/lib/names";
import { plainBasisName } from "@/lib/plain";
import { DecisionLinks } from "./DecisionLinks";
import { orderCases, useWaterCases } from "./useWater";

interface StepRowProps {
  card: ProposalCard;
  now: string;
  number?: number;
  /** The step with the earliest deadline carries the basis line. */
  first: boolean;
  showBasis?: boolean;
  /** One line of consequence and the link under the deadline: a step that sits inside an expanded table row. */
  compact?: boolean;
}

/** One decision in a chain: number, title and tier, why it is late, its links, and the deadline on the right. */
export function StepRow({ card, now, number, first, showBasis = true, compact = false }: StepRowProps) {
  const basis = card.case.clock.consequence_basis;
  const mark = actionMark(card.action_type, card.params);
  const title = decisionTitle(card.title);
  return (
    <li
      className={cn(
        "grid grid-cols-[22px_minmax(0,1fr)_auto] gap-x-3 border-b border-hair",
        compact ? "py-2" : "py-2.5",
      )}
      data-testid="water-case"
    >
      {number === undefined ? (
        <span aria-hidden className="mx-auto mt-2 size-1.5 rounded-full bg-faint" />
      ) : (
        <span
          aria-hidden
          className={cn(
            "mt-0.5 grid size-[22px] place-items-center rounded-full border-[1.5px] text-[11.5px] font-bold",
            number === 1 ? "border-primary bg-primary text-on-primary" : "border-faint",
          )}
        >
          {number}
        </span>
      )}
      <div className="min-w-0">
        <p className="m-0 flex items-start gap-1.5 text-[14px] leading-snug font-semibold">
          <mark.Icon className="mt-[3px] size-3.5 shrink-0 text-muted" aria-hidden />
          <span className="min-w-0">
            <span className="sr-only">{mark.label}: </span>
            {title}
            <span className="ml-2 inline-block align-middle">
              <TierBadge tier={card.tier} />
            </span>
          </span>
        </p>
        {compact ? (
          <p className="m-0 mt-0.5 truncate text-[13px] text-muted" title={plainIds(card.case.clock.if_late)}>
            {plainIds(card.case.clock.if_late)}
          </p>
        ) : (
          <p className="m-0 mt-0.5 text-[13px] text-muted">
            {plainIds(card.case.clock.if_late)} <DecisionLinks proposalId={card.proposal_id} title={title} />
          </p>
        )}
        {first && showBasis && (
          <p className="m-0 mt-1 text-[12px] text-muted">
            Based on{" "}
            {basis.basis_id.startsWith("inject.") ? (
              <Citation citation={basis.citation ?? "Scripted exercise data (synthetic)"} />
            ) : (
              <>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span>{plainBasisName(basis.basis_id)}</span>
                  </TooltipTrigger>
                  <TooltipContent>{`${basis.basis_id} v${basis.basis_version}`}</TooltipContent>
                </Tooltip>
                {basis.citation && (
                  <>
                    {", "}
                    <Citation citation={basis.citation} />
                  </>
                )}
              </>
            )}
          </p>
        )}
      </div>
      {compact ? (
        <div className="flex flex-col items-end gap-0.5">
          <ClockText at={card.effective_decide_by_utc} now={now} column />
          <DecisionLinks proposalId={card.proposal_id} title={title} />
        </div>
      ) : (
        <ClockText at={card.effective_decide_by_utc} now={now} column />
      )}
    </li>
  );
}

export function earliestId(cards: ProposalCard[]): string | undefined {
  return [...cards].sort(
    (a, b) => Date.parse(a.effective_decide_by_utc) - Date.parse(b.effective_decide_by_utc),
  )[0]?.proposal_id;
}

/** The PS-17 plan tab: the critical path in order beside the other open water decisions. */
export function ClocksContainer({ now }: { now: string }) {
  const { cards, isPending, error } = useWaterCases();
  const { chain, others } = orderCases(cards);
  const firstId = earliestId([...chain, ...others]);
  if (error) {
    return <EmptyState role="alert" icon={Route} title="Couldn't load water decisions." />;
  }
  if (isPending) return <LoadingState label="Loading water decisions…" />;
  if (cards.length === 0) {
    return <EmptyState icon={Route} title="No open water decisions." />;
  }
  return (
    <div className="grid gap-x-10 px-8 py-5 min-[1100px]:grid-cols-2">
      <section aria-labelledby="plan-steps" className="min-w-0">
        <h3 id="plan-steps" className="m-0 mb-1 flex items-center gap-1 text-[16px] font-bold">
          Steps in order
          <InfoTip term="clock" />
        </h3>
        {chain.length > 0 ? (
          <ol className="m-0 list-none p-0" aria-label="Critical path, in order">
            {chain.map((c, i) => (
              <StepRow
                key={c.proposal_id}
                card={c}
                now={now}
                number={i + 1}
                first={c.proposal_id === firstId}
              />
            ))}
          </ol>
        ) : (
          <p className="m-0 py-3 text-[13px] text-muted">No steps wait on each other right now.</p>
        )}
      </section>
      <section aria-labelledby="plan-others" className="min-w-0">
        <h3 id="plan-others" className="m-0 mb-1 text-[16px] font-bold">
          Other open decisions
        </h3>
        {others.length > 0 ? (
          <ul className="m-0 list-none p-0" aria-label="Other open water decisions">
            {others.map((c) => (
              <StepRow key={c.proposal_id} card={c} now={now} first={c.proposal_id === firstId} />
            ))}
          </ul>
        ) : (
          <p className="m-0 py-3 text-[13px] text-muted">No other water decisions are open.</p>
        )}
      </section>
    </div>
  );
}
