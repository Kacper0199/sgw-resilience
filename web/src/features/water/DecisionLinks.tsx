import { ChevronRight } from "lucide-react";
import { Link } from "react-router";
import { cn } from "@/lib/cn";
import { decisionHref } from "@/lib/links";

interface DecisionLinksProps {
  proposalId: string;
  /** Names the target for screen readers: "View decision: Send the fuel truck". */
  title?: string;
  label?: string;
  className?: string;
}

/** The "View decision ›" link into Decisions. */
export function DecisionLinks({ proposalId, title, label = "View decision", className }: DecisionLinksProps) {
  const to = decisionHref(proposalId);
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-x-3 gap-y-1", className)}>
      <Link
        to={to}
        aria-label={title ? `${label}: ${title}` : undefined}
        className="inline-flex items-center gap-0.5 text-[13px] font-semibold text-blue-ink hover:underline"
      >
        {label}
        <ChevronRight className="size-3.5" aria-hidden />
      </Link>
    </span>
  );
}
