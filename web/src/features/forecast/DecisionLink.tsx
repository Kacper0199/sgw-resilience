import { ChevronRight } from "lucide-react";
import { Link } from "react-router";
import { useProposals } from "@/features/decisions/useQueue";
import { decisionHref } from "@/lib/links";

const linkClass = "inline-flex items-center text-[13px] font-semibold text-blue-ink hover:underline";

/** "View decision ›" for each decision the row depends on; one link says so plainly, several carry their titles. */
export function DecisionRefs({ caseIds }: { caseIds: readonly string[] }) {
  const proposals = useProposals();
  if (caseIds.length === 0) return null;
  const found = caseIds.flatMap((id) => proposals.data?.find((p) => p.decision_case_id === id) ?? []);
  if (found.length === 0) return <span className="text-[12px] text-muted">No proposal yet</span>;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
      {found.map((p) => (
        <Link
          key={p.proposal_id}
          to={decisionHref(p.proposal_id)}
          aria-label={`View decision: ${p.title}`}
          className={linkClass}
        >
          {found.length === 1 ? "View decision" : p.title}
          <ChevronRight className="size-3.5" aria-hidden />
        </Link>
      ))}
    </span>
  );
}
