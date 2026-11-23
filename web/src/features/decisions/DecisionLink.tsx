import { ChevronRight } from "lucide-react";
import { Link } from "react-router";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";

import { decisionHref } from "@/lib/links";

export { decisionHref };

/** A decision named in text: its id in mono, blue, underlined on hover. Tooltip "Open this decision". */
export function DecisionIdLink({
  proposalId,
  label,
  className,
}: {
  proposalId: string;
  /** What to show; the decision case id, for example "DC-D3-PS17-POWER". */
  label: string;
  className?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          to={decisionHref(proposalId)}
          className={cn("font-mono text-[12px] text-blue-ink hover:underline", className)}
        >
          {label}
        </Link>
      </TooltipTrigger>
      <TooltipContent>Open this decision</TooltipContent>
    </Tooltip>
  );
}

/** "View decision ›" at the end of a row that is about one decision. */
export function ViewDecisionLink({
  proposalId,
  className,
  children = "View decision",
}: {
  proposalId: string;
  className?: string;
  children?: string;
}) {
  return (
    <Link
      to={decisionHref(proposalId)}
      className={cn(
        "inline-flex items-center gap-0.5 text-[13px] font-semibold whitespace-nowrap text-blue-ink hover:underline",
        className,
      )}
    >
      {children}
      <ChevronRight className="size-3.5" aria-hidden />
    </Link>
  );
}
