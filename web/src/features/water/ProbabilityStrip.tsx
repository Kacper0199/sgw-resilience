import { percentPpm } from "./format";

interface Mark {
  /** The advisory time under the mark, for example "11:00 ET". */
  label: string;
  ppm: number;
}

interface Props {
  from: Mark;
  to: Mark;
  /** SGW's own trigger, as a share (0.10). */
  threshold: number | undefined;
  width?: number;
}

const H = 84;
const PAD = 14;
const TRACK_Y = 34;

/**
 * The chance of low pressure on a 0 to 20% line. Everything above SGW's trigger is shaded: crossing it means the
 * boil-water notice is due. The hollow circle is the previous advisory, the filled mark the latest; each carries
 * its value and its advisory time.
 */
export function ProbabilityStrip({ from, to, threshold, width = 460 }: Props) {
  const W = width;
  const top = Math.max(0.2, Math.ceil(Math.max(from.ppm / 1e6, to.ppm / 1e6, threshold ?? 0) * 10 + 1) / 10);
  const x = (share: number) => PAD + (share / top) * (W - 2 * PAD);
  const over = threshold !== undefined && to.ppm / 1e6 >= threshold;
  const mark = over ? "var(--warn-mark)" : "var(--ink)";
  const label = `Previous advisory ${from.label} ${percentPpm(from.ppm)}, latest advisory ${to.label} ${percentPpm(to.ppm)}${
    threshold === undefined
      ? ""
      : `, notice trigger ${(threshold * 100).toFixed(0)}%${over ? ", crossed" : ", not crossed"}`
  }`;
  const xf = x(from.ppm / 1e6);
  const xt = x(to.ppm / 1e6);
  const xThreshold = threshold === undefined ? null : x(threshold);
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={label}
      className="w-full max-w-[520px]"
      data-testid="probability-strip"
    >
      <rect
        x={PAD}
        y={TRACK_Y - 3}
        width={W - 2 * PAD}
        height={6}
        rx={3}
        fill="var(--hair-strong)"
        opacity={0.6}
      />
      {xThreshold !== null && (
        <>
          <rect
            x={xThreshold}
            y={TRACK_Y - 12}
            width={W - PAD - xThreshold}
            height={24}
            fill="var(--warn-mark)"
            opacity={0.14}
            data-testid="trigger-zone"
          />
          <line
            x1={xThreshold}
            x2={xThreshold}
            y1={TRACK_Y - 14}
            y2={TRACK_Y + 14}
            stroke="var(--warn)"
            strokeWidth={2}
          />
          <text
            x={xThreshold}
            y={H - 4}
            textAnchor="middle"
            fontSize={11.5}
            fill="var(--warn)"
            fontWeight={600}
          >
            Notice trigger {(threshold ?? 0) * 100}%
          </text>
          <text x={W - PAD} y={H - 4} textAnchor="end" fontSize={11} fill="var(--muted)">
            Above: notice due
          </text>
        </>
      )}
      <line x1={xf} x2={xt} y1={TRACK_Y} y2={TRACK_Y} stroke={mark} strokeWidth={3} />
      <circle cx={xf} cy={TRACK_Y} r={6} fill="var(--surface)" stroke="var(--ink)" strokeWidth={2} />
      {over ? (
        <polygon
          points={`${xt},${TRACK_Y - 8} ${xt + 8},${TRACK_Y} ${xt},${TRACK_Y + 8} ${xt - 8},${TRACK_Y}`}
          fill={mark}
        />
      ) : (
        <circle cx={xt} cy={TRACK_Y} r={6} fill={mark} />
      )}
      <text x={xf} y={TRACK_Y - 18} textAnchor="middle" fontSize={12} fontWeight={600} fill="var(--ink)">
        {percentPpm(from.ppm)}
      </text>
      <text
        x={xt}
        y={TRACK_Y - 18}
        textAnchor="middle"
        fontSize={12}
        fontWeight={700}
        fill={over ? "var(--warn)" : "var(--ink)"}
      >
        {percentPpm(to.ppm)}
      </text>
      <text x={xf} y={TRACK_Y + 28} textAnchor="middle" fontSize={11} fill="var(--muted)">
        {from.label}
      </text>
      <text x={xt} y={TRACK_Y + 28} textAnchor="middle" fontSize={11} fill="var(--muted)">
        {to.label}
      </text>
    </svg>
  );
}
