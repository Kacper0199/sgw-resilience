import { GLOSSARY, type GlossaryKey } from "@/content/glossary";
import { cn } from "@/lib/cn";
import { InfoTip } from "./InfoTip";

/** The plain "Info" link next to a page title; it opens the same toggletip as the (i) button. */
export function InfoLink({ term, className }: { term: GlossaryKey; className?: string }) {
  return (
    <InfoTip term={term}>
      <button
        type="button"
        aria-label={`Info: ${GLOSSARY[term].term}`}
        className={cn("text-[13px] font-medium text-blue-ink hover:underline", className)}
      >
        Info
      </button>
    </InfoTip>
  );
}
