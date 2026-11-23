import { ChevronRight } from "lucide-react";
import type * as React from "react";
import { Link } from "react-router";
import { CountBadge } from "@/components/sgw";
import { decisionHref } from "@/lib/links";
import { formatDayET, formatET, formatZ } from "@/lib/time";
import { decisionTitle } from "../decisions/actionTypes";
import { useProposals } from "../decisions/useQueue";

/** A decision by its title, linked to it; plain "Decision" until the queue has loaded. */
export function DecisionName({ proposalId }: { proposalId: string }) {
  const title = useProposals().data?.find((p) => p.proposal_id === proposalId)?.title;
  return (
    <Link to={decisionHref(proposalId)} title="Open this decision" className="text-blue-ink hover:underline">
      {title ? decisionTitle(title) : "Decision"}
    </Link>
  );
}

/** The text link that ends a row about one decision. */
export function ViewDecision({ id }: { id: string }) {
  return (
    <Link
      to={decisionHref(id)}
      className="inline-flex items-center gap-0.5 text-[13px] font-semibold whitespace-nowrap text-blue-ink hover:underline"
    >
      View decision
      <ChevronRight className="size-3.5" aria-hidden />
    </Link>
  );
}

/** "25 Sep, 22:15 ET" with the UTC time on a grey second line. */
export function Stamp({ iso, utc = true }: { iso: string; utc?: boolean }) {
  return (
    <>
      <span className="block tnum">
        {formatDayET(iso)}, {formatET(iso)}
      </span>
      {utc && <span className="block text-[12px] text-muted tnum">{formatZ(iso)}</span>}
    </>
  );
}

/** One section of the report: 18/24 bold heading over a 1 px rule, anchored for the contents list. */
export function ReportSection({
  id,
  title,
  count,
  actions,
  children,
}: {
  id: string;
  title: string;
  count?: number;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-h`} className="scroll-mt-6 min-w-0" data-section={id}>
      <header className="mb-3 flex items-center gap-2 border-b border-hair pb-2">
        <h2 id={`${id}-h`} className="m-0 text-[18px] leading-6 font-bold">
          {title}
        </h2>
        {count !== undefined && <CountBadge count={count} />}
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

/** Table text lines up with the section heading instead of sitting 12 px in. */
export const FLUSH = "[&_tr>:first-child]:pl-0 [&_tr>:last-child]:pr-0";
