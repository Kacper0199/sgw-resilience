import { ChevronDown, ListTree } from "lucide-react";
import { cn } from "@/lib/cn";
import { formatDayET, formatET } from "@/lib/time";
import { formatGust, formatOut, formatRisk, NO_DATA } from "./format";
import type { Domain } from "./layerData";
import type { LayerState } from "./layers";
import { FLOOD_LABEL, FLOOD_ORDER, WARNING_LABEL, WARNING_ORDER } from "./observed";
import type { SurgeStarts } from "./surges";

interface Props {
  layers: LayerState;
  domain: Domain | null;
  hasSteps: boolean;
  /** The forecast layers are history: they say "last advisory" instead of "now". */
  forecastIsHistory?: boolean;
  /** Which steps of the selected decision have no place on the map, in words; null when all do. */
  unplacedNote: string | null;
  /** Which parts of the storm track the advisory has: the track so far, the forecast and the position now. */
  track: { past: boolean; future: boolean; now: boolean };
  surgeRange: SurgeStarts | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The advisory bar is not on the map, so the legend sits at the bottom edge. */
  low?: boolean;
}

const RAMP = [1, 2, 3, 4, 5];
const WARNING_VAR = {
  hurricane: "--map-warning-hurricane",
  tropical_storm: "--map-warning-tropical",
  flood: "--map-warning-flood",
  flash_flood: "--map-warning-flash-flood",
  tornado: "--map-warning-tornado",
} as const;

const startText = (iso: string) => `${formatDayET(iso)} ${formatET(iso).replace(" ET", "")}`;

const Entry = ({ children }: { children: React.ReactNode }) => (
  <li className="flex min-h-5 items-center gap-2 text-[12px] text-ink">{children}</li>
);

const Group = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section aria-label={title} className="flex flex-col gap-0.5 border-t border-hair px-3 py-1.5">
    <h3 className="m-0 text-[11px] font-semibold tracking-wide text-muted uppercase">{title}</h3>
    <ul className="m-0 flex list-none flex-col gap-0.5 p-0">{children}</ul>
  </section>
);

const Grid = ({ children }: { children: React.ReactNode }) => (
  <li className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-[12px] text-ink-2">{children}</li>
);

const Cell = ({ children }: { children: React.ReactNode }) => (
  <span className="flex items-center gap-1.5 whitespace-nowrap">{children}</span>
);

/** What the symbols on the map mean, for the layers that are on. It carries no switches: those are in the layer panel. */
export function MapLegend({
  layers,
  domain,
  hasSteps,
  forecastIsHistory = false,
  unplacedNote,
  track,
  surgeRange,
  open,
  onOpenChange,
  low = false,
}: Props) {
  const fill = layers.county === "wind" ? "wind" : layers.county === "outages" ? "outages" : "risk";
  const range =
    domain === null
      ? null
      : fill === "risk"
        ? `${formatRisk(domain.min)} to ${formatRisk(domain.max)}`
        : fill === "outages"
          ? `${formatOut(Math.round(domain.min))} to ${formatOut(Math.round(domain.max))}`
          : `${formatGust(domain.min)} to ${formatGust(domain.max)}`;
  const last = forecastIsHistory ? " in the last advisory" : "";
  const fillTitle =
    fill === "outages"
      ? "Customers out now"
      : fill === "risk"
        ? `Outage risk${forecastIsHistory ? ", last forecast" : ""}`
        : `Peak gust${forecastIsHistory ? ", last forecast" : ""}`;
  const assets = layers.power || layers.water;
  const storm = layers.track || layers.cone;
  return (
    <section
      aria-label="Legend"
      data-testid="map-legend"
      className={cn(
        "absolute right-3 z-10 flex max-w-[calc(100%-24px)] flex-col items-end gap-2",
        low ? "bottom-3" : "bottom-16",
      )}
    >
      {open ? (
        <div className="w-[196px] rounded-lg bg-surface shadow-float">
          <button
            type="button"
            aria-expanded
            onClick={() => onOpenChange(false)}
            className="flex h-9 w-full items-center justify-between rounded-lg pr-2.5 pl-3 text-left"
          >
            <span className="text-[14px] font-bold">Legend</span>
            <ChevronDown className="size-4 text-muted" aria-hidden />
          </button>
          {layers.county !== "none" && (
            <Group title={fillTitle}>
              <li className="flex flex-col gap-0.5">
                <span
                  aria-hidden
                  className="flex h-2 w-full overflow-hidden rounded-[2px] border border-hair-strong"
                >
                  {RAMP.map((i) => (
                    <span
                      key={i}
                      className="h-full flex-1"
                      style={{
                        background: fill === "outages" ? `var(--map-surge-${6 - i})` : `var(--risk-${i})`,
                      }}
                    />
                  ))}
                </span>
                <span className="flex justify-between text-[11px] text-muted tnum">
                  <span>{range ? range.split(" to ")[0] : "Low"}</span>
                  <span>{range ? range.split(" to ")[1] : "High"}</span>
                </span>
              </li>
              {fill === "outages" && (
                <Entry>
                  <span
                    aria-hidden
                    className="inline-block h-2.5 w-3.5 shrink-0 rounded-[2px] border border-hair-strong"
                    style={{
                      backgroundImage:
                        "repeating-linear-gradient(135deg, var(--map-nodata) 0 1px, transparent 1px 4px)",
                    }}
                  />
                  {NO_DATA}
                </Entry>
              )}
            </Group>
          )}
          {layers.warnings && (
            <Group title="Warnings">
              <Grid>
                {WARNING_ORDER.map((k) => (
                  <Cell key={k}>
                    <span
                      aria-hidden
                      className="inline-block h-2.5 w-3.5 shrink-0 rounded-[2px] border-2"
                      style={{ borderColor: `var(${WARNING_VAR[k]})` }}
                    />
                    {WARNING_LABEL[k]}
                  </Cell>
                ))}
              </Grid>
            </Group>
          )}
          {layers.gauges && (
            <Group title="River gauges">
              <Grid>
                {FLOOD_ORDER.map((k) => (
                  <Cell key={k}>
                    <span
                      aria-hidden
                      className={cn(
                        "inline-block shrink-0 rounded-full",
                        k === "below" ? "size-1.5" : "size-2.5",
                      )}
                      style={{ background: `var(--map-gauge-${k})` }}
                    />
                    {k === "below" ? "Below flood" : FLOOD_LABEL[k].replace(" flood", "")}
                  </Cell>
                ))}
              </Grid>
            </Group>
          )}
          {layers.surges && (
            <Group title="First surge at (ET)">
              <li className="flex flex-col gap-0.5">
                <span
                  aria-hidden
                  className="flex h-2 w-full overflow-hidden rounded-[2px] border border-hair-strong"
                >
                  {RAMP.map((i) => (
                    <span key={i} className="h-full flex-1" style={{ background: `var(--map-surge-${i})` }} />
                  ))}
                </span>
                {surgeRange && (
                  <span className="flex justify-between text-[11px] text-muted tnum">
                    <span>{startText(surgeRange.first)}</span>
                    {surgeRange.last !== surgeRange.first && <span>{startText(surgeRange.last)}</span>}
                  </span>
                )}
              </li>
              {surgeRange && surgeRange.recent > 0 && (
                <Entry>
                  <span
                    aria-hidden
                    className="inline-block h-2.5 w-3.5 shrink-0 rounded-[2px] border-[1.5px] border-dashed border-ink"
                  />
                  Began in the last 3 h
                </Entry>
              )}
            </Group>
          )}
          {layers.wind && (
            <Group title="Airport wind">
              <Entry>
                <svg aria-hidden width="14" height="16" viewBox="0 0 14 16" className="shrink-0">
                  <path
                    d="M7 1 L12 8 H8.6 V15 H5.4 V8 H2 Z"
                    fill="var(--ink)"
                    stroke="var(--surface)"
                    strokeWidth="1"
                    strokeLinejoin="round"
                  />
                </svg>
                Peak gust, downwind
              </Entry>
            </Group>
          )}
          {(assets || storm || hasSteps) && (
            <Group title="Map">
              {layers.power && (
                <Entry>
                  <span aria-hidden className="size-2.5 shrink-0 rounded-full bg-ink" /> Power asset
                </Entry>
              )}
              {layers.water && (
                <Entry>
                  <span
                    aria-hidden
                    className="size-2.5 shrink-0 rounded-[2px] border border-surface bg-[var(--map-asset-water)] ring-1 ring-[var(--map-asset-water)]"
                  />{" "}
                  Water asset
                </Entry>
              )}
              {layers.track && track.past && (
                <Entry>
                  <span aria-hidden className="inline-block w-3.5 shrink-0 border-t-[2.6px] border-ink" />
                  Storm track so far
                </Entry>
              )}
              {layers.track && track.future && (
                <Entry>
                  <span
                    aria-hidden
                    className="inline-block w-3.5 shrink-0 border-t-2 border-dashed border-ink"
                  />
                  Forecast track{last}
                </Entry>
              )}
              {layers.track && track.now && (
                <Entry>
                  <span
                    aria-hidden
                    className="inline-flex size-3.5 shrink-0 items-center justify-center rounded-full border-2 border-link bg-link/20"
                  >
                    <span className="size-1.5 rounded-full bg-link" />
                  </span>
                  {forecastIsHistory ? "Storm position at last advisory" : "Storm position now"}
                </Entry>
              )}
              {layers.cone && (
                <Entry>
                  <span
                    aria-hidden
                    className="inline-block h-2.5 w-3.5 shrink-0 rounded-[2px] border border-link bg-link/15"
                  />
                  Storm cone{last}
                </Entry>
              )}
              {hasSteps && layers.steps && (
                <Entry>
                  <span
                    aria-hidden
                    className="inline-flex size-4 shrink-0 items-center justify-center rounded-full bg-primary text-[10px] font-semibold text-on-primary"
                  >
                    1
                  </span>
                  Decision step
                </Entry>
              )}
              {hasSteps && layers.steps && unplacedNote && (
                <li className="pl-6 text-[11px] leading-4 text-muted">{unplacedNote}</li>
              )}
            </Group>
          )}
        </div>
      ) : (
        <button
          type="button"
          aria-expanded={false}
          aria-label="Open legend"
          data-testid="legend-toggle"
          onClick={() => onOpenChange(true)}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-surface px-2.5 text-[13px] font-semibold text-ink shadow-float hover:bg-surface-2"
        >
          <ListTree className="size-4" aria-hidden />
          Legend
        </button>
      )}
    </section>
  );
}
