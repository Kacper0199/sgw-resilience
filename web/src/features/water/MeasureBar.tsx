interface Props {
  value: number;
  low: number | null;
  high: number | null;
  target: number | null;
  baseline: number | null;
  baselineName: string | null;
}

const W = 520;
const PAD = 6;
const x = (share: number) => PAD + share * (W - 2 * PAD);
const pct = (share: number) => `${Math.round(share * 100)}%`;

/** A 0 to 100% bar: the measured share, its 95% range, the target tick and the baseline marker. Amber fill when the target is missed. */
export function MeasureBar({ value, low, high, target, baseline, baselineName }: Props) {
  const label = `Measured ${pct(value)}${low !== null && high !== null ? `, 95% range ${pct(low)} to ${pct(high)}` : ""}${
    target !== null ? `, target ${pct(target)}` : ""
  }${baseline !== null ? `, ${baselineName ?? "baseline"} ${pct(baseline)}` : ""}`;
  const short = target !== null && value < target;
  return (
    <svg
      viewBox={`0 0 ${W} 62`}
      role="img"
      aria-label={label}
      className="h-[62px] w-full max-w-[520px]"
      data-testid="measure-bar"
    >
      <rect x={PAD} y={24} width={W - 2 * PAD} height={10} rx={5} fill="var(--chart-track)" />
      <rect
        x={PAD}
        y={24}
        width={Math.max(value * (W - 2 * PAD), 6)}
        height={10}
        rx={5}
        fill={short ? "var(--warn-mark)" : "var(--chart-1)"}
      />
      {low !== null && high !== null && (
        <g stroke="var(--surface)" strokeWidth={2}>
          <line x1={x(low)} x2={x(high)} y1={29} y2={29} />
          <line x1={x(low)} x2={x(low)} y1={25} y2={33} />
          <line x1={x(high)} x2={x(high)} y1={25} y2={33} />
        </g>
      )}
      {baseline !== null && (
        <g>
          <polygon
            points={`${x(baseline)},37 ${x(baseline) - 4},44 ${x(baseline) + 4},44`}
            fill="var(--muted)"
          />
          <text x={x(baseline)} y={57} textAnchor="start" fontSize={11} fill="var(--muted)" dx={-4}>
            {baselineName ?? "Baseline"} {pct(baseline)}
          </text>
        </g>
      )}
      {target !== null && (
        <g>
          <line x1={x(target)} x2={x(target)} y1={16} y2={42} stroke="var(--ink)" strokeWidth={1.5} />
          <text x={x(target) + 4} y={12} textAnchor="start" fontSize={11} fill="var(--ink)">
            Target {pct(target)}
          </text>
        </g>
      )}
      <text
        x={x(value)}
        y={12}
        textAnchor="end"
        fontSize={12}
        fontWeight={600}
        fill={short ? "var(--warn)" : "var(--ink)"}
      >
        {pct(value)}
      </text>
    </svg>
  );
}
