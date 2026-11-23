import { cn } from "@/lib/cn";

interface PressureBarProps {
  psi: number;
  floorPsi: number;
  /** Full scale of the bar; the mockup uses 80 psi. */
  maxPsi?: number;
  width?: number;
  className?: string;
}

/** A thin bar for one pressure against its minimum: blue fill, ink tick at the minimum, amber fill below it. */
export function PressureBar({ psi, floorPsi, maxPsi = 80, width = 120, className }: PressureBarProps) {
  const below = psi < floorPsi;
  const at = (v: number) => Math.max(0, Math.min(1, v / maxPsi)) * width;
  return (
    <svg
      role="img"
      aria-label={`${psi.toFixed(1)} psi, minimum ${floorPsi.toFixed(1)} psi`}
      width={width}
      height={14}
      viewBox={`0 0 ${width} 14`}
      className={cn("shrink-0", className)}
    >
      <rect x={0} y={3} width={width} height={8} rx={4} fill="var(--chart-track)" />
      <rect
        x={0}
        y={3}
        width={Math.max(at(psi), 4)}
        height={8}
        rx={4}
        fill={below ? "var(--warn-mark)" : "var(--chart-1)"}
      />
      <line x1={at(floorPsi)} x2={at(floorPsi)} y1={0} y2={14} stroke="var(--ink)" strokeWidth={1.5} />
    </svg>
  );
}
