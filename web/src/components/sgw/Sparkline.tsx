import { useId } from "react";
import { cn } from "@/lib/cn";

interface SparklineProps {
  values: readonly number[];
  /** Spoken summary, for example "Pressure, last 12 hours, falling". Required: the line itself is not text. */
  label: string;
  width?: number;
  height?: number;
  /** Value of a limit to draw as a thin tick line, for example the boil-water trigger. */
  limit?: number;
  /** Fixed scale for bounded quantities, so noise does not look dramatic: pressure 50 to 70 psi. */
  range?: readonly [number, number];
  /** Colour only when the trend needs attention. */
  tone?: "neutral" | "warn" | "crit";
  className?: string;
}

const STROKE = { neutral: "var(--muted)", warn: "var(--warn-mark)", crit: "var(--crit)" } as const;

/** Small inline trend line for next to a value. Inline SVG, no axes; the last point is marked. */
export function Sparkline({
  values,
  label,
  width = 72,
  height = 22,
  limit,
  range,
  tone = "neutral",
  className,
}: SparklineProps) {
  const titleId = useId();
  if (values.length < 2) {
    return (
      <span role="img" aria-label={`${label}: no data`} className={cn("inline-block text-faint", className)}>
        <svg width={width} height={height} aria-hidden>
          <line
            x1="0"
            x2={width}
            y1={height / 2}
            y2={height / 2}
            stroke="currentColor"
            strokeDasharray="3 3"
          />
        </svg>
      </span>
    );
  }
  const all = limit === undefined ? values : [...values, limit];
  const min = range ? Math.min(range[0], ...all) : Math.min(...all);
  const max = range ? Math.max(range[1], ...all) : Math.max(...all);
  const span = max - min || 1;
  const pad = 3;
  const x = (i: number) => pad + (i * (width - pad * 2)) / (values.length - 1);
  const y = (v: number) => height - pad - ((v - min) / span) * (height - pad * 2);
  const points = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const last = values.length - 1;
  return (
    <svg
      role="img"
      aria-labelledby={titleId}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn("inline-block shrink-0 align-middle", className)}
    >
      <title id={titleId}>{label}</title>
      {limit !== undefined && (
        <line
          x1="0"
          x2={width}
          y1={y(limit)}
          y2={y(limit)}
          stroke="var(--hair-strong)"
          strokeDasharray="2 2"
        />
      )}
      <polyline
        points={points}
        fill="none"
        stroke={STROKE[tone]}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={x(last)} cy={y(values[last] as number)} r="2" fill={STROKE[tone]} />
    </svg>
  );
}
