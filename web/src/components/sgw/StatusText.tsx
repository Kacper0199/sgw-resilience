import type { UiSeverity } from "@/contracts/vocab.gen";
import { cn } from "@/lib/cn";

export const SEVERITY_LABEL: Record<UiSeverity, string> = {
  critical: "Critical",
  severe: "Severe",
  elevated: "Elevated",
  advisory: "Minor",
  normal: "Normal",
  unknown_stale: "No data",
};

const TONE: Record<UiSeverity, string> = {
  critical: "text-crit",
  severe: "text-crit",
  elevated: "text-warn",
  advisory: "text-muted",
  normal: "text-muted",
  unknown_stale: "text-faint",
};

function Shape({ level }: { level: UiSeverity }) {
  const line = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinejoin: "round" } as const;
  switch (level) {
    case "critical":
      return <polygon points="8,1 15,8 8,15 1,8" fill="currentColor" />;
    case "severe":
      return <polygon points="8,1.5 14.5,8 8,14.5 1.5,8" {...line} />;
    case "elevated":
      return <polygon points="8,2 15,14 1,14" {...line} />;
    case "advisory":
      return <circle cx="8" cy="8" r="5.5" {...line} />;
    case "normal":
      return (
        <path
          d="M3 8.5l3.2 3.2L13 4.5"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      );
    case "unknown_stale":
      return <circle cx="8" cy="8" r="5.5" {...line} strokeWidth={1.5} strokeDasharray="2.5 2" />;
  }
}

interface StatusTextProps {
  level: UiSeverity;
  /** Replaces the default word, for example "Elevated (watch)". */
  label?: string;
  className?: string;
}

/** Shape plus word, no fill. Colour appears only when something is abnormal; shape and word always carry the level. */
export function StatusText({ level, label, className }: StatusTextProps) {
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 whitespace-nowrap font-medium", TONE[level], className)}
      data-severity={level}
    >
      <svg viewBox="0 0 16 16" className="size-3.5 shrink-0" aria-hidden>
        <Shape level={level} />
      </svg>
      <span>{label ?? SEVERITY_LABEL[level]}</span>
    </span>
  );
}
