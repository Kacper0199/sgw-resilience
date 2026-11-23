import type * as React from "react";
import type { GlossaryKey } from "@/content/glossary";
import { cn } from "@/lib/cn";
import { InfoTip } from "./InfoTip";

export interface KeyNumber {
  label: string;
  value: React.ReactNode;
  /** One grey line below the number. */
  line?: React.ReactNode;
  /** The number turns amber or red only when it needs attention. */
  tone?: "warn" | "crit";
  info?: GlossaryKey;
  testId?: string;
}

/** Four numbers separated by hairlines, no box. Two by two below 820 px. */
export function KeyNumberStrip({
  items,
  className,
  ...props
}: { items: readonly KeyNumber[]; className?: string } & Omit<
  React.ComponentProps<"dl">,
  "children" | "style"
>) {
  return (
    <dl
      className={cn(
        "m-0 grid shrink-0 grid-cols-2 gap-y-4 px-8 py-3 min-[820px]:grid-cols-[repeat(var(--n),minmax(0,1fr))] [@media(max-height:799px)]:gap-y-2 [@media(max-height:799px)]:py-2",
        className,
      )}
      style={{ "--n": items.length } as React.CSSProperties}
      {...props}
    >
      {items.map((n) => (
        <div
          key={n.label}
          data-testid={n.testId}
          className="min-w-0 border-l border-divider pl-5 first:border-l-0 first:pl-0 max-[819px]:odd:border-l-0 max-[819px]:odd:pl-0"
        >
          <dt className="flex items-center gap-1 text-[12px] font-semibold text-muted">
            {n.label}
            {n.info && <InfoTip term={n.info} />}
          </dt>
          <dd
            className={cn(
              "m-0 text-figure font-semibold whitespace-nowrap tnum [@media(max-height:799px)]:text-[22px] [@media(max-height:799px)]:leading-7",
              n.tone === "warn" && "text-warn",
              n.tone === "crit" && "text-crit",
            )}
          >
            {n.value}
          </dd>
          {n.line && (
            <dd className="m-0 text-[12px] text-muted [@media(max-height:799px)]:hidden">{n.line}</dd>
          )}
        </div>
      ))}
    </dl>
  );
}
