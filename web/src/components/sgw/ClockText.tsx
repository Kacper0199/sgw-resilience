import { cn } from "@/lib/cn";
import { formatAbsolute, formatRelative, urgencyOf } from "@/lib/time";

interface ClockTextProps {
  /** ISO instant the clock counts to. */
  at: string;
  /** ISO instant that is "now" on the scenario clock. */
  now: string;
  stacked?: boolean;
  /** Right-aligned table cell: relative over the absolute time. */
  column?: boolean;
  className?: string;
}

const TONE = { normal: "text-ink", soon: "text-warn", missed: "text-crit" } as const;

/** "in 12 h 4 m" with "23:29 ET (03:29Z)" (ET first). Neutral until under 60 minutes, amber, red only when missed. */
export function ClockText({ at, now, stacked = false, column = false, className }: ClockTextProps) {
  const tone = TONE[urgencyOf(at, now)];
  if (column) {
    return (
      <span className={cn("flex flex-col text-end leading-tight tnum whitespace-nowrap", className)}>
        <span className={cn("text-[13px] font-medium", tone)}>{formatRelative(at, now)}</span>
        <span className="font-mono text-[11px] text-muted">{formatAbsolute(at)}</span>
      </span>
    );
  }
  return (
    <span
      className={cn(
        "tnum whitespace-nowrap",
        stacked ? "flex flex-col leading-tight" : "inline-flex items-baseline gap-1.5",
        className,
      )}
    >
      <span className={cn("font-medium", tone)}>{formatRelative(at, now)}</span>
      <span className="font-mono text-[12px] text-muted">{formatAbsolute(at)}</span>
    </span>
  );
}
