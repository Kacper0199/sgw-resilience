import { ChevronRight } from "lucide-react";
import { Link } from "react-router";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { decisionHref } from "@/lib/links";

/** A decision's id as a link: mono, blue-ink, underline on hover, tooltip "Open this decision". */
export function DecisionId({
  id,
  label,
  className,
}: {
  id: string;
  /** What to show when the link target (a proposal id) differs from the id readers know, the decision case id. */
  label?: string;
  className?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          to={decisionHref(id)}
          className={cn("font-mono text-[12px] text-blue-ink hover:underline", className)}
        >
          {label ?? id}
        </Link>
      </TooltipTrigger>
      <TooltipContent>Open this decision</TooltipContent>
    </Tooltip>
  );
}

/** The "View decision ›" text link for a row that is about one decision. */
export function ViewDecision({
  id,
  label = "View decision",
  className,
}: {
  id: string;
  label?: string;
  className?: string;
}) {
  return (
    <Link
      to={decisionHref(id)}
      className={cn(
        "inline-flex items-center gap-0.5 text-[13px] font-semibold whitespace-nowrap text-blue-ink hover:underline",
        className,
      )}
    >
      {label}
      <ChevronRight aria-hidden className="size-3.5" />
    </Link>
  );
}
