import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { plainCitation } from "@/lib/rules";

/** The rule or procedure behind a number, in plain words; the exact clause appears on hover and focus. */
export function Citation({ citation }: { citation: string }) {
  const { label, clause } = plainCitation(citation);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="cursor-help border-0 bg-transparent p-0 text-inherit decoration-dotted underline-offset-2 hover:underline"
        >
          {label}
        </button>
      </TooltipTrigger>
      <TooltipContent>{clause}</TooltipContent>
    </Tooltip>
  );
}
