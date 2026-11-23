import { useQuery } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { Citation, StatusIndicator } from "@/components/sgw";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { ClockWaterfall, ProposalCard } from "@/lib/api";
import { api } from "@/lib/api";
import { plainIds } from "@/lib/names";
import { plainBasisName } from "@/lib/plain";
import { clockStatus } from "./DecisionClock";
import { humanizeKey } from "./Envelope";
import { EvidenceTab } from "./EvidenceTab";
import { PaneSection } from "./PaneSection";
import { ReasonTip } from "./ReasonTip";
import { Waterfall } from "./Waterfall";

type Basis = ClockWaterfall["consequence_basis"];

function BasisLine({ label, basis }: { label: string; basis: Basis }) {
  return (
    <p className="m-0">
      {label}{" "}
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="text-ink-2">{plainBasisName(basis.basis_id)}</span>
        </TooltipTrigger>
        <TooltipContent>{`${basis.basis_id} v${basis.basis_version}`}</TooltipContent>
      </Tooltip>
      {basis.citation && (
        <>
          {", "}
          <Citation citation={basis.citation} />
        </>
      )}
    </p>
  );
}

/** The Deadline tab: the verdict in one line, the deadline on a timeline, what happens if it is late, checks before signing. */
export function BasisTab({ card, now }: { card: ProposalCard; now: string }) {
  const { data, isPending, error } = useQuery({
    queryKey: ["proposals", card.proposal_id, "clock"],
    queryFn: () => api.clock(card.proposal_id),
  });
  const preconditions = Object.entries(card.preconditions);
  const status = clockStatus(card, now);
  return (
    <div className="flex flex-col" data-testid="basis">
      {isPending ? (
        <Skeleton className="h-32" />
      ) : error || !data ? (
        <p className="m-0 text-[13px] text-error" role="alert">
          Couldn't load the deadline details.
        </p>
      ) : (
        <div className="mb-4">
          <Waterfall
            data={data}
            now={now}
            decideRange={[card.case.clock.decide_by_p10_utc, card.case.clock.decide_by_p90_utc]}
            heldBy={card.case.chain?.find((c) => c.decision_case_id === data.bound_by_case_id)?.title}
            info={
              <ReasonTip label="Where the numbers come from" title="Where the numbers come from">
                <BasisLine label="Impact start:" basis={data.consequence_basis} />
                <BasisLine label="Lead time:" basis={data.lead_time_basis} />
              </ReasonTip>
            }
          />
        </div>
      )}
      <div className="mb-5 flex flex-col gap-1 text-[13px] text-muted" data-testid="decision-clock">
        {status.status === "missed" && <StatusIndicator status={status.status} label={status.label} />}
        <p className="m-0">If late: {plainIds(card.case.clock.if_late).replace(/\.$/, "")}</p>
      </div>
      {preconditions.length > 0 && (
        <PaneSection title="Checks before you sign">
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-[14px]" data-testid="preconditions">
            {preconditions.map(([key, ok]) => (
              <li key={key} className="flex items-center gap-2">
                {ok ? (
                  <Check className="size-4 text-ok" aria-hidden />
                ) : (
                  <X className="size-4 text-warn" aria-hidden />
                )}
                <span>{humanizeKey(key)}</span>
                <span className={ok ? "text-muted" : "font-medium text-warn"}>{ok ? "Met" : "Not met"}</span>
              </li>
            ))}
          </ul>
        </PaneSection>
      )}
      <EvidenceTab card={card} />
    </div>
  );
}
