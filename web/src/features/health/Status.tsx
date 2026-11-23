import { Check, CircleDashed, Diamond, Triangle } from "lucide-react";
import type * as React from "react";
import { cn } from "@/lib/cn";

export type Tone = "ok" | "warn" | "bad" | "idle";

const TONE = {
  ok: { icon: Check, text: "text-muted" },
  warn: { icon: Triangle, text: "text-warn" },
  bad: { icon: Diamond, text: "text-crit" },
  idle: { icon: CircleDashed, text: "text-faint" },
} as const;

/** Shape plus words, no fill. Grey when normal; amber or red only when something needs attention. */
export function Mark({
  tone,
  children,
  className,
}: {
  tone: Tone;
  children: React.ReactNode;
  className?: string;
}) {
  const { icon: Icon, text } = TONE[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-[13px] font-medium whitespace-nowrap",
        text,
        className,
      )}
    >
      <Icon className="size-3.5 shrink-0" strokeWidth={tone === "ok" ? 2.2 : 1.7} aria-hidden />
      {children}
    </span>
  );
}

/** The one plain-language line under the tabs; the detail sits below it. Flat: a rule, no box. */
export function StatusLine({
  tone,
  headline,
  detail,
  testId,
}: {
  tone: Tone;
  headline: string;
  detail?: string;
  testId?: string;
}) {
  const { icon: Icon, text } = TONE[tone];
  return (
    <div
      role="status"
      data-testid={testId ?? "status-line"}
      data-tone={tone}
      className="flex items-start gap-2.5 border-b border-hair px-8 py-3"
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", text)} strokeWidth={1.7} aria-hidden />
      <p className="m-0 min-w-0 text-[14px] leading-snug">
        <span className="font-semibold">{headline}</span>
        {detail && <span className="text-muted"> {detail}</span>}
      </p>
    </div>
  );
}
