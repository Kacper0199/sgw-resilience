import { cn } from "@/lib/cn";

const TONE = {
  neutral: "bg-surface-3 text-ink-2",
  warn: "bg-warn-soft text-warn",
  crit: "bg-crit-soft text-crit",
} as const;

/** Grey pill; amber or red only when the count itself is a problem. */
export function CountBadge({
  count,
  tone = "neutral",
  className,
}: {
  count: number | string;
  tone?: keyof typeof TONE;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-block min-w-[20px] rounded-full px-1.5 text-center text-[11px] leading-5 font-semibold tnum",
        TONE[tone],
        className,
      )}
    >
      {count}
    </span>
  );
}
