import type * as React from "react";
import { approvalDetail, approvalLabel } from "@/lib/approval";
import { cn } from "@/lib/cn";
import { type Domain, DomainMark } from "./DomainMark";

/** Outline chip that names the kind of thing: Water, Power, PS-17. A `domain` adds the small coloured marker. */
export function Tag({
  className,
  domain,
  children,
  ...props
}: { domain?: Domain } & React.ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-sm border border-hair-strong px-1.5 text-[12px] leading-none whitespace-nowrap text-ink-2",
        className,
      )}
      {...props}
    >
      {domain && <DomainMark domain={domain} />}
      {children}
    </span>
  );
}

/** The approval an item needs, in words ("2 teams sign"); the tooltip says it as a sentence. */
export function Tier({ tier, className, ...props }: { tier: string } & React.ComponentProps<"span">) {
  return (
    <span
      title={approvalDetail(tier)}
      className={cn(
        "inline-flex items-center text-[12px] leading-none whitespace-nowrap text-ink-2",
        tier === "T3" && "font-medium text-ink",
        className,
      )}
      {...props}
    >
      {approvalLabel(tier)}
    </span>
  );
}
