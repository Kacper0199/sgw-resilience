import type { ClockWaterfall } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDuration, formatET, formatETOn, formatEtZ } from "@/lib/time";
import { domainFor, position, ticks } from "./timeAxis";

const MIN = 60_000;

interface Props {
  data: ClockWaterfall;
  now: string;
  /** The API's 80% range of the decide-by (`case.clock.decide_by_p10_utc`, `decide_by_p90_utc`). */
  decideRange?: [string, string];
  /** The (i) that explains where the numbers come from; it sits under the time legend, clear of the axis labels. */
  info?: React.ReactNode;
  /** The decision that holds this deadline earlier, named for the tooltip of the "moved earlier" line. */
  heldBy?: string;
}

const LABEL_COLUMN = "grid-cols-[84px_1fr]";

const Row = ({ label, children }: { label: React.ReactNode; children: React.ReactNode }) => (
  <div className={cn("grid h-9 items-center gap-3", LABEL_COLUMN)}>
    <span className="text-[12px] leading-tight whitespace-nowrap text-muted">{label}</span>
    <div className="relative h-full">{children}</div>
  </div>
);

/** Harm starts (with its 80% range), minus the time the action takes, equals decide-by, on a real time axis. */
const EDGE_PCT = 85;

export function Waterfall({ data, now, decideRange, info, heldBy }: Props) {
  const nowMs = Date.parse(now);
  const conseq = Date.parse(data.consequence_utc);
  const [cLo, cHi] = data.consequence_range_utc.map(Date.parse) as [number, number];
  const decide = Date.parse(data.decide_by_utc);
  const effective = Date.parse(data.effective_decide_by_utc);
  const held = effective < decide;
  const [decideLo, decideHi] = decideRange?.map(Date.parse) ?? [decide, decide];
  const { domain, nowOutside } = domainFor(nowMs, Math.min(decideLo, effective), cHi);
  const pos = (t: number) => `${Math.min(100, Math.max(0, position(domain, t)))}%`;
  const width = (a: number, b: number) => `${Math.max(0.8, position(domain, b) - position(domain, a))}%`;
  const grid = ticks(domain);
  const nowLeft = nowOutside ? "0%" : pos(nowMs);

  return (
    <figure className="relative isolate m-0" data-testid="waterfall" aria-label="Deadline on a timeline">
      <div className={cn("grid gap-3", LABEL_COLUMN)}>
        <span className="flex items-start gap-0.5 pt-0.5 text-[12px] whitespace-nowrap text-muted">
          <span>
            Time
            <br />
            ET (UTC)
          </span>
          {info}
        </span>
        <div className="relative h-9 border-b border-hair">
          {grid.map((t) => (
            <span
              key={t.ms}
              className={cn(
                "absolute top-0 text-[11px] leading-tight whitespace-nowrap text-muted tnum",
                position(domain, t.ms) > EDGE_PCT
                  ? "-translate-x-full text-right"
                  : "-translate-x-1/2 text-center",
              )}
              style={{ left: pos(t.ms) }}
            >
              <span className="block text-ink">{t.et}</span>
              <span className="block font-mono text-[10px]">{t.z}</span>
            </span>
          ))}
        </div>
      </div>
      <div className="relative">
        <div className="pointer-events-none absolute inset-y-0 right-0 left-[96px]" aria-hidden>
          {grid.map((t) => (
            <span key={t.ms} className="absolute inset-y-0 w-px bg-hair" style={{ left: pos(t.ms) }} />
          ))}
          <span
            className="absolute inset-y-0 z-10 w-0.5 bg-link"
            style={{ left: nowLeft }}
            data-testid="waterfall-now"
          />
        </div>
        <Row label="Impact starts">
          <span
            className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-subtle ring-1 ring-hair-strong"
            style={{ left: pos(cLo), width: width(cLo, cHi) }}
            title={`80% range ${formatET(data.consequence_range_utc[0])}–${formatET(data.consequence_range_utc[1])}`}
          />
          <span
            className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rotate-45 border-2 border-ink bg-surface"
            style={{ left: pos(conseq) }}
          />
        </Row>
        <Row label="Lead time">
          <span
            className="absolute top-1/2 h-3 -translate-y-1/2 rounded-sm border border-link bg-row-sel"
            style={{ left: pos(decide), width: width(decide, conseq) }}
          />
          <span
            className="absolute top-1/2 -translate-y-1/2 pr-2 text-[12px] font-medium whitespace-nowrap text-ink tnum"
            style={{ right: `calc(100% - ${pos(decide)})` }}
          >
            {formatDuration(data.action_lead_time_min)}
          </span>
        </Row>
        <Row label={<span className="font-medium text-ink">Decide by</span>}>
          {decideRange && (
            <span
              className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-subtle ring-1 ring-hair-strong"
              style={{ left: pos(decideLo), width: width(decideLo, decideHi) }}
            />
          )}
          <span
            data-testid="waterfall-own"
            data-at={data.decide_by_utc}
            className={cn(
              "absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rotate-45",
              held ? "border-2 border-ink bg-surface" : "bg-ink",
            )}
            style={{ left: pos(decide) }}
          />
          {held && (
            <span
              data-testid="waterfall-effective"
              data-at={data.effective_decide_by_utc}
              className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rotate-45 bg-ink"
              style={{ left: pos(effective) }}
            />
          )}
        </Row>
      </div>
      <div className={cn("mt-1 grid gap-3 text-[12px] text-muted", LABEL_COLUMN)}>
        <span />
        <span className={cn("inline-flex items-center gap-1.5", nowOutside && "text-ink")}>
          <span aria-hidden className="inline-block h-3 w-0.5 bg-link" />
          Now {formatEtZ(now)}
          {nowOutside &&
            `, ${formatDuration(Math.round((Math.min(decideLo, effective) - nowMs) / MIN))} before this range`}
        </span>
      </div>
      {held && (
        <p
          className="m-0 mt-1 text-[12px] whitespace-nowrap text-muted tnum"
          data-testid="waterfall-held"
          title={heldBy ? `Held earlier by: ${heldBy}` : undefined}
        >
          Own deadline ◇ {formatETOn(data.decide_by_utc, now)}, held to ◆{" "}
          {formatETOn(data.effective_decide_by_utc, now)} by a linked decision
        </p>
      )}
    </figure>
  );
}
