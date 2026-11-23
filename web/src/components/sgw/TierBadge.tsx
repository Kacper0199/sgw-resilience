import { tierGlossaryKey } from "@/content/glossary";
import type { Tier as TierName } from "@/contracts/vocab.gen";
import { approvalLabel } from "@/lib/approval";
import { cn } from "@/lib/cn";
import { InfoTip } from "./InfoTip";

/** The approval label as a button; its toggletip names the tier and what it asks. */
export function TierBadge({ tier, className }: { tier: TierName; className?: string }) {
  return (
    <InfoTip term={tierGlossaryKey(tier)}>
      <button
        type="button"
        aria-label={`Approval: ${approvalLabel(tier)}`}
        className={cn(
          "inline-flex h-5 items-center rounded-sm text-[12px] leading-none whitespace-nowrap text-ink-2 underline decoration-dotted underline-offset-2 hover:text-ink",
          className,
        )}
      >
        {approvalLabel(tier)}
      </button>
    </InfoTip>
  );
}
