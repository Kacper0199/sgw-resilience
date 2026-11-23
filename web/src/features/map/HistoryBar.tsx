import { Pause, Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { formatDayET, formatET } from "@/lib/time";
import type { AdvisoryIndexItem } from "./types";

const PLAY_STEP_MS = 1500;

interface Props {
  advisories: AdvisoryIndexItem[];
  /** The advisory shown on the map. */
  label: string | null;
  /** The newest issued advisory: what "Live" means. */
  liveLabel: string | null;
  onSelect: (label: string) => void;
  /** The shown advisory has no outage forecast to colour the counties with. */
  noForecast: boolean;
  /** Sits in the page flow instead of floating over a map. */
  inline?: boolean;
  /** No advisory follows the newest one, so it is the final advisory, not "live". */
  final?: boolean;
}

const timeOf = (a: AdvisoryIndexItem) => `${formatDayET(a.issued_utc)} ${formatET(a.issued_utc)}`;

/** One stop per issued advisory, spaced by time. Local to the map: it never moves the shared replay clock. */
export function HistoryBar({
  advisories,
  label,
  liveLabel,
  onSelect,
  noForecast,
  inline = false,
  final = false,
}: Props) {
  const stops = useMemo(
    () => [...advisories].sort((a, b) => Date.parse(a.issued_utc) - Date.parse(b.issued_utc)),
    [advisories],
  );
  const [playing, setPlaying] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const index = Math.max(
    0,
    stops.findIndex((s) => s.advisory_label === label),
  );
  const live = label === liveLabel;
  const selected = stops[index];

  useEffect(() => {
    if (!playing) return;
    if (index >= stops.length - 1) {
      setPlaying(false);
      return;
    }
    const timer = setTimeout(
      () => onSelect((stops[index + 1] as AdvisoryIndexItem).advisory_label),
      PLAY_STEP_MS,
    );
    return () => clearTimeout(timer);
  }, [playing, index, stops, onSelect]);

  if (stops.length < 2 || !selected) return null;

  const first = Date.parse((stops[0] as AdvisoryIndexItem).issued_utc);
  const span = Date.parse((stops[stops.length - 1] as AdvisoryIndexItem).issued_utc) - first || 1;
  const pct = (a: AdvisoryIndexItem) => ((Date.parse(a.issued_utc) - first) / span) * 100;
  const go = (i: number) => {
    const next = stops[Math.min(stops.length - 1, Math.max(0, i))];
    if (next) onSelect(next.advisory_label);
  };
  const days = stops.filter(
    (s, i) =>
      i === 0 || formatDayET(s.issued_utc) !== formatDayET((stops[i - 1] as AdvisoryIndexItem).issued_utc),
  );
  const shown = stops[hover ?? index] ?? selected;

  return (
    <div
      data-testid="history-bar"
      className={cn(
        "@container mx-auto flex max-w-[760px] flex-col",
        inline ? "relative" : "absolute inset-x-3 bottom-3 z-10",
      )}
    >
      <div className="flex h-11 items-center gap-2 rounded-lg bg-surface pr-2 pl-1.5 shadow-float">
        <button
          type="button"
          aria-label={playing ? "Pause" : "Play advisories"}
          onClick={() => {
            if (!playing && live) go(0);
            setPlaying(!playing);
          }}
          className="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-ink hover:bg-surface-2"
        >
          {playing ? <Pause className="size-4" aria-hidden /> : <Play className="size-4" aria-hidden />}
        </button>
        <div className="relative mx-3 h-full min-w-0 flex-1">
          <div
            role="slider"
            tabIndex={0}
            aria-label="Advisory history"
            aria-valuemin={0}
            aria-valuemax={stops.length - 1}
            aria-valuenow={index}
            aria-valuetext={`${timeOf(selected)} advisory${live ? (final ? ", final" : ", live") : ""}`}
            onKeyDown={(e) => {
              const move: Record<string, number> = {
                ArrowLeft: index - 1,
                ArrowDown: index - 1,
                ArrowRight: index + 1,
                ArrowUp: index + 1,
                Home: 0,
                End: stops.length - 1,
              };
              if (e.key in move) {
                e.preventDefault();
                setPlaying(false);
                go(move[e.key] as number);
              }
            }}
            className="absolute inset-0 rounded-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue"
          />
          <span aria-hidden className="absolute inset-x-0 top-[17px] h-0.5 rounded-full bg-hair-strong" />
          {stops.map((s, i) => (
            <button
              key={s.advisory_label}
              type="button"
              tabIndex={-1}
              aria-hidden
              data-testid="history-stop"
              data-active={i === index}
              onClick={() => {
                setPlaying(false);
                go(i);
              }}
              onPointerEnter={() => setHover(i)}
              onPointerLeave={() => setHover(null)}
              style={{ left: `${pct(s)}%` }}
              className="absolute top-[6px] flex size-6 -translate-x-1/2 items-center justify-center rounded-full"
            >
              <span
                className={cn(
                  "block rounded-full border-2 border-surface transition-[width,height]",
                  i === index
                    ? "size-4 bg-blue ring-2 ring-blue/30"
                    : "size-2.5 bg-hair-strong hover:bg-muted",
                  i < index && "bg-blue/50",
                )}
              />
            </button>
          ))}
          {days.map((s) => (
            <span
              key={s.advisory_label}
              aria-hidden
              style={{ left: `${pct(s)}%` }}
              className="absolute bottom-0.5 -translate-x-1/2 text-[10.5px] whitespace-nowrap text-muted"
            >
              {formatDayET(s.issued_utc)}
            </span>
          ))}
        </div>
        <span
          className={cn(
            "w-[104px] shrink-0 text-right text-[12px] tnum @[520px]:block",
            noForecast ? "block text-muted" : "hidden text-ink-2",
          )}
        >
          {noForecast ? "Not forecast yet" : timeOf(shown)}
        </span>
        <button
          type="button"
          aria-pressed={live}
          onClick={() => {
            setPlaying(false);
            if (liveLabel) onSelect(liveLabel);
          }}
          className={cn(
            "inline-flex h-7 min-w-[104px] shrink-0 items-center justify-center gap-1.5 rounded-full px-2.5 text-[12px] font-semibold",
            live ? "bg-primary text-on-primary" : "border border-hair-strong text-ink hover:bg-surface-2",
          )}
        >
          <span aria-hidden className={cn("size-1.5 rounded-full", live ? "bg-on-primary" : "bg-muted")} />
          {live ? (final ? "Final advisory" : "Live") : final ? "Back to final" : "Back to live"}
        </button>
      </div>
    </div>
  );
}
