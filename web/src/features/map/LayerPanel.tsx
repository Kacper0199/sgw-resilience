import { ChevronDown, Layers, X } from "lucide-react";
import { useId } from "react";
import { SegmentedControl } from "@/components/sgw";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/cn";
import { formatDayET, formatET } from "@/lib/time";
import { type LayerState, type Utility, utilityOf, withUtility } from "./layers";

interface Props {
  layers: LayerState;
  onChange: (next: LayerState) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  hasSelection: boolean;
  hasSteps: boolean;
  onClearSelection: () => void;
  /** The numbers are switched on but the map is zoomed out too far to show them. */
  valuesNeedZoom: boolean;
  /** Set once the forecast is history: the forecast switches move under "Last forecast", after what was observed. */
  forecastHistory?: { finalAdvisoryUtc: string | null } | null;
  /** A scripted exercise: customers out and the storm track only. */
  scripted?: boolean;
}

function Row({
  label,
  on,
  onChange,
  name,
  nested = false,
  hint,
}: {
  label: string;
  on: boolean;
  onChange: (on: boolean) => void;
  name?: string;
  nested?: boolean;
  hint?: string;
}) {
  const id = useId();
  return (
    <div className={cn("flex flex-col", nested && "pl-4")}>
      <div className="flex h-[26px] items-center justify-between gap-3">
        <label htmlFor={id} className={cn("cursor-pointer text-[13px]", nested ? "text-ink-2" : "text-ink")}>
          {label}
        </label>
        <Switch id={id} aria-label={name} checked={on} onCheckedChange={onChange} />
      </div>
      {hint && <p className="m-0 -mt-1 pb-1 text-[11px] text-muted">{hint}</p>}
    </div>
  );
}

const Group = ({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) => (
  <section aria-label={title} className="flex flex-col border-t border-hair px-3 py-1.5">
    <h3 className="m-0 flex h-5 items-center text-[11px] font-semibold tracking-wide text-muted uppercase">
      {title}
    </h3>
    {note && <p className="m-0 pb-0.5 text-[11px] text-muted">{note}</p>}
    {children}
  </section>
);

/** Layer switches on the map. Collapsed to one small button by default; solid surface so it reads over any basemap. */
export function LayerPanel({
  layers,
  onChange,
  open,
  onOpenChange,
  hasSelection,
  hasSteps,
  onClearSelection,
  valuesNeedZoom,
  forecastHistory,
  scripted = false,
}: Props) {
  const set = (patch: Partial<LayerState>) => onChange({ ...layers, ...patch });
  const assetsOn = layers.power || layers.water;
  const zoomHint = valuesNeedZoom ? "Zoom in to see them" : undefined;
  const fillOn = (kind: "risk" | "wind" | "outages", on: boolean): Partial<LayerState> =>
    on
      ? {
          county: kind,
          values:
            layers.values === "none" ? "none" : kind === "risk" ? "risk" : kind === "wind" ? "gust" : "out",
        }
      : { county: "none", values: "none" };
  const finalAt = forecastHistory?.finalAdvisoryUtc;
  const forecastNote = finalAt ? `Final advisory, ${formatDayET(finalAt)} ${formatET(finalAt)}` : undefined;
  const clear = hasSelection && (
    <button
      type="button"
      onClick={onClearSelection}
      className="inline-flex h-8 items-center gap-1 rounded-lg bg-surface px-2.5 text-[13px] font-medium text-ink shadow-float hover:bg-surface-2"
    >
      <X className="size-3.5" aria-hidden />
      Clear selection
    </button>
  );
  return (
    <div className="absolute top-3 left-3 z-10 flex max-w-[calc(100%-72px)] flex-col items-start gap-2">
      {open ? (
        <section
          aria-label="Map layers"
          data-testid="layer-panel"
          className="w-[208px] max-w-full rounded-lg bg-surface shadow-float"
        >
          <header className="flex h-9 items-center justify-between pr-1.5 pl-3">
            <h2 className="m-0 text-[14px] font-bold">Layers</h2>
            <button
              type="button"
              aria-expanded
              aria-label="Collapse layers"
              onClick={() => onOpenChange(false)}
              className="inline-flex size-7 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
            >
              <ChevronDown className="size-4" aria-hidden />
            </button>
          </header>
          {scripted ? (
            <Group title="Scripted exercise">
              <Row
                label="Customers out now"
                on={layers.county === "outages"}
                onChange={(on) => set(fillOn("outages", on))}
              />
              {layers.county === "outages" && (
                <Row
                  nested
                  label="Values"
                  name="Customers out values"
                  on={layers.values === "out"}
                  onChange={(on) => set({ values: on ? "out" : "none" })}
                  hint={layers.values === "out" ? zoomHint : undefined}
                />
              )}
              <Row label="Storm track" on={layers.track} onChange={(on) => set({ track: on, cone: false })} />
            </Group>
          ) : forecastHistory ? (
            <>
              <Group title="Observed">
                <Row
                  label="Customers out now"
                  on={layers.county === "outages"}
                  onChange={(on) => set(fillOn("outages", on))}
                />
                {layers.county === "outages" && (
                  <Row
                    nested
                    label="Values"
                    name="Customers out values"
                    on={layers.values === "out"}
                    onChange={(on) => set({ values: on ? "out" : "none" })}
                    hint={layers.values === "out" ? zoomHint : undefined}
                  />
                )}
                <Row label="Warnings" on={layers.warnings} onChange={(on) => set({ warnings: on })} />
                <Row label="River gauges" on={layers.gauges} onChange={(on) => set({ gauges: on })} />
                <Row label="Airport wind" on={layers.wind} onChange={(on) => set({ wind: on })} />
                {layers.wind && (
                  <Row
                    nested
                    label="Gust values"
                    name="Airport gust values"
                    on={layers.windValues}
                    onChange={(on) => set({ windValues: on })}
                  />
                )}
                <Row label="Outage surges" on={layers.surges} onChange={(on) => set({ surges: on })} />
              </Group>
              <Group title={forecastHistory ? "Last forecast" : "Forecast"} note={forecastNote}>
                <Row
                  label="Outage risk"
                  on={layers.county === "risk"}
                  onChange={(on) => set(fillOn("risk", on))}
                />
                {layers.county === "risk" && (
                  <Row
                    nested
                    label="Values"
                    name="Outage risk values"
                    on={layers.values === "risk"}
                    onChange={(on) => set({ values: on ? "risk" : "none" })}
                    hint={layers.values === "risk" ? zoomHint : undefined}
                  />
                )}
                <Row
                  label="Peak gust"
                  on={layers.county === "wind"}
                  onChange={(on) => set(fillOn("wind", on))}
                />
                {layers.county === "wind" && (
                  <Row
                    nested
                    label="Values"
                    name="Peak gust values"
                    on={layers.values === "gust"}
                    onChange={(on) => set({ values: on ? "gust" : "none" })}
                    hint={layers.values === "gust" ? zoomHint : undefined}
                  />
                )}
                <Row
                  label="Storm track and cone"
                  on={layers.track || layers.cone}
                  onChange={(on) => set({ track: on, cone: on })}
                />
              </Group>
            </>
          ) : (
            <>
              <Group title={forecastHistory ? "Last forecast" : "Forecast"} note={forecastNote}>
                <Row
                  label="Outage risk"
                  on={layers.county === "risk"}
                  onChange={(on) => set(fillOn("risk", on))}
                />
                {layers.county === "risk" && (
                  <Row
                    nested
                    label="Values"
                    name="Outage risk values"
                    on={layers.values === "risk"}
                    onChange={(on) => set({ values: on ? "risk" : "none" })}
                    hint={layers.values === "risk" ? zoomHint : undefined}
                  />
                )}
                <Row
                  label="Peak gust"
                  on={layers.county === "wind"}
                  onChange={(on) => set(fillOn("wind", on))}
                />
                {layers.county === "wind" && (
                  <Row
                    nested
                    label="Values"
                    name="Peak gust values"
                    on={layers.values === "gust"}
                    onChange={(on) => set({ values: on ? "gust" : "none" })}
                    hint={layers.values === "gust" ? zoomHint : undefined}
                  />
                )}
                <Row
                  label="Storm track and cone"
                  on={layers.track || layers.cone}
                  onChange={(on) => set({ track: on, cone: on })}
                />
              </Group>
              <Group title="Observed">
                <Row
                  label="Customers out now"
                  on={layers.county === "outages"}
                  onChange={(on) => set(fillOn("outages", on))}
                />
                {layers.county === "outages" && (
                  <Row
                    nested
                    label="Values"
                    name="Customers out values"
                    on={layers.values === "out"}
                    onChange={(on) => set({ values: on ? "out" : "none" })}
                    hint={layers.values === "out" ? zoomHint : undefined}
                  />
                )}
                <Row label="Warnings" on={layers.warnings} onChange={(on) => set({ warnings: on })} />
                <Row label="River gauges" on={layers.gauges} onChange={(on) => set({ gauges: on })} />
                <Row label="Airport wind" on={layers.wind} onChange={(on) => set({ wind: on })} />
                {layers.wind && (
                  <Row
                    nested
                    label="Gust values"
                    name="Airport gust values"
                    on={layers.windValues}
                    onChange={(on) => set({ windValues: on })}
                  />
                )}
                <Row label="Outage surges" on={layers.surges} onChange={(on) => set({ surges: on })} />
              </Group>
            </>
          )}
          <Group title="Assets">
            <Row label="Show assets" on={assetsOn} onChange={(on) => set({ power: on, water: on })} />
            <SegmentedControl<Utility>
              label="Utility"
              value={utilityOf(layers)}
              onValueChange={(u) => onChange(withUtility(layers, u))}
              options={[
                { value: "all", label: "All" },
                { value: "power", label: "Power" },
                { value: "water", label: "Water" },
              ]}
              className="mt-0.5 mb-0.5 h-8 w-full [&>button]:flex-1 [&>button]:px-2"
            />
          </Group>
          {hasSteps && (
            <Group title="Decision">
              <Row label="Steps" on={layers.steps} onChange={(on) => set({ steps: on })} />
            </Group>
          )}
          {clear && (
            <div className="border-t border-hair p-2 [&>button]:w-full [&>button]:bg-surface-2 [&>button]:shadow-none">
              {clear}
            </div>
          )}
        </section>
      ) : (
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-expanded={false}
            aria-label="Open layers"
            data-testid="layer-toggle"
            onClick={() => onOpenChange(true)}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-surface px-2.5 text-[13px] font-semibold text-ink shadow-float hover:bg-surface-2"
          >
            <Layers className="size-4" aria-hidden />
            Layers
          </button>
          {clear}
        </div>
      )}
    </div>
  );
}
