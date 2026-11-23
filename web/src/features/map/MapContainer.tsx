import { Map as MapIcon, MapPinOff } from "lucide-react";
import { parseAsString, useQueryState } from "nuqs";
import { useRef, useState } from "react";
import { Link } from "react-router";
import { EmptyState } from "@/components/sgw";
import { cn } from "@/lib/cn";
import { usePhase } from "@/lib/PhaseProvider";
import { forecastIsHistory } from "@/lib/phase";
import { isPack } from "@/lib/scenarios";
import { useScenario } from "@/sse/useScenarioNow";
import { proposalForAssets, unplacedNote } from "./chain";
import { HistoryBar } from "./HistoryBar";
import { LayerPanel } from "./LayerPanel";
import { defaultLayers, type LayerState, observedOn, stormOn } from "./layers";
import { MapLegend } from "./MapLegend";
import MapView from "./MapView";
import type { StepStop } from "./Overlays";
import { useMapData } from "./useMapData";
import { useReducedMotion } from "./useReducedMotion";
import { useStoredFlag } from "./useStoredFlag";

interface Props {
  selectedProposalId: string | null;
  /** A click on an asset selects the most urgent open decision that targets it. Without this, the `d` URL parameter
   * the queue also reads is set. The map never filters the queue. */
  onSelectProposal?: (proposalId: string) => void;
  /** `strip` is the preview on top of the Decisions pane; `full` fills the Map page. */
  variant?: "strip" | "full";
  /** Controlled layers and advisory choice (the Map page owns them). */
  layers?: LayerState;
  onLayersChange?: (next: LayerState) => void;
  advisoryLabel?: string | null;
  onAdvisoryChange?: (label: string) => void;
  /** Reports the assets under a click, so the Map page can show its side panel. */
  onAssetsPicked?: (assetIds: string[]) => void;
  onStepPicked?: (stop: StepStop) => void;
  activeStepKey?: string | null;
  selectedAssetIds?: ReadonlySet<string>;
  onClearSelection?: () => void;
  /** The county the page was opened on (`?county=`): outlined and framed when nothing else is selected. */
  focusCounty?: string | null;
}

const NARROW_MAP = 900;
const LAYERS_KEY = "sgw.map.layers-open";
const LEGEND_KEY = "sgw.map.legend-open";

export default function MapContainer({
  selectedProposalId,
  onSelectProposal,
  variant = "strip",
  layers: controlledLayers,
  onLayersChange,
  advisoryLabel,
  onAdvisoryChange,
  onAssetsPicked,
  onStepPicked,
  activeStepKey = null,
  selectedAssetIds,
  onClearSelection,
  focusCounty = null,
}: Props) {
  const full = variant === "full";
  const phase = usePhase();
  const history = forecastIsHistory(phase);
  const scripted = isPack(useScenario().data?.scenario);
  const layers = controlledLayers ?? defaultLayers(history, !full, scripted);
  const [failed, setFailed] = useState(false);
  const root = useRef<HTMLElement>(null);
  const [layersOpen, setLayersOpen] = useStoredFlag(LAYERS_KEY, false);
  const [legendOpen, setLegendOpen] = useStoredFlag(LEGEND_KEY, false);
  const [valuesZoomed, setValuesZoomed] = useState(true);
  const narrow = () => (root.current?.clientWidth ?? NARROW_MAP) < NARROW_MAP;
  const openLayers = (open: boolean) => {
    setLayersOpen(open);
    if (open && narrow()) setLegendOpen(false);
  };
  const openLegend = (open: boolean) => {
    setLegendOpen(open);
    if (open && narrow()) setLayersOpen(false);
  };
  const reducedMotion = useReducedMotion();
  const forecastShown = layers.county === "risk" || layers.county === "wind" || stormOn(layers);
  const advisoryBar = !history || forecastShown;
  const data = useMapData({
    selectedProposalId,
    selectedAssetIds,
    advisoryLabel,
    county: layers.county,
    observed: full && observedOn(layers),
    surges: full && layers.surges,
    scripted,
  });
  const [, setSelectedInUrl] = useQueryState("d", parseAsString.withOptions({ history: "replace" }));

  const onAssetClick = (assetIds: string[]) => {
    onAssetsPicked?.(assetIds);
    const id = proposalForAssets(assetIds, data.cards);
    if (!id) return;
    if (onSelectProposal) onSelectProposal(id);
    else void setSelectedInUrl(id);
  };
  const onStepClick = (stop: StepStop) => {
    if (full) return onStepPicked?.(stop);
    const card = data.cards.find((c) => c.decision_case_id === stop.caseId);
    if (card) onSelectProposal?.(card.proposal_id);
  };

  return (
    <section
      ref={root}
      aria-label="Map"
      className={cn("relative min-h-0 overflow-hidden bg-canvas", "h-full")}
      data-variant={variant}
    >
      {failed ? (
        <EmptyState role="alert" icon={MapPinOff} title="The map can't run on this device." />
      ) : (
        <>
          <p className="sr-only">
            Map of the SGW service area with county outlines, assets, risk and the storm track.
          </p>
          <div className="absolute inset-0" data-testid="map">
            <MapView
              basemap={data.basemap}
              assets={data.assetList}
              values={data.values}
              outagesReported={data.outagesReported}
              domain={data.domain}
              layers={layers}
              storm={data.storm}
              observations={full ? data.observations : undefined}
              surges={full ? data.surges : undefined}
              surgeAsOf={data.surgeAsOf}
              surgeStarts={data.surgeRange}
              selectedIds={data.selectedIds}
              stops={data.stops}
              activeStepKey={activeStepKey}
              reducedMotion={reducedMotion}
              preview={!full}
              dimSteps={full && data.label !== data.current?.advisory_label}
              focusCounty={focusCounty}
              onAssetClick={onAssetClick}
              onStepClick={onStepClick}
              onValuesZoomChange={setValuesZoomed}
              onFailure={() => setFailed(true)}
            />
          </div>
          {full ? (
            <>
              <LayerPanel
                layers={layers}
                onChange={(next) => onLayersChange?.(next)}
                open={layersOpen}
                onOpenChange={openLayers}
                hasSteps={data.stops.length > 0}
                forecastHistory={history ? { finalAdvisoryUtc: phase.finalAdvisoryUtc } : null}
                scripted={scripted}
                valuesNeedZoom={layers.values !== "none" && !valuesZoomed}
                hasSelection={
                  Boolean(selectedProposalId) || Boolean(focusCounty) || (selectedAssetIds?.size ?? 0) > 0
                }
                onClearSelection={() => onClearSelection?.()}
              />
              {!scripted &&
                data.issued.length > 1 &&
                (!history || layers.county === "risk" || layers.county === "wind" || stormOn(layers)) && (
                  <HistoryBar
                    final={phase.advisoriesOver}
                    advisories={data.issued}
                    label={data.label}
                    liveLabel={data.current?.advisory_label ?? null}
                    onSelect={(label) => onAdvisoryChange?.(label)}
                    noForecast={data.noForecast}
                  />
                )}
              <MapLegend
                layers={layers}
                domain={data.domain}
                hasSteps={data.stops.length > 0}
                forecastIsHistory={history}
                low={data.issued.length < 2 || !advisoryBar}
                unplacedNote={unplacedNote(data.unplaced)}
                track={{
                  past: data.storm.past.features.length > 0,
                  future: data.storm.future.features.length > 0,
                  now: data.storm.now.features.length > 0,
                }}
                surgeRange={data.surgeRange}
                open={legendOpen}
                onOpenChange={openLegend}
              />
            </>
          ) : (
            <>
              <Link
                to={selectedProposalId ? `/map?d=${encodeURIComponent(selectedProposalId)}` : "/map"}
                className="absolute top-2 right-2 z-10 inline-flex h-7 items-center gap-1.5 rounded-md bg-surface px-2.5 text-[13px] font-semibold text-blue-ink shadow-float hover:underline"
              >
                <MapIcon className="size-4" aria-hidden />
                Open map
              </Link>
              {data.domain && (
                <p
                  data-testid="map-legend"
                  className="absolute bottom-2 left-2 z-10 m-0 inline-flex items-center gap-2 rounded-md bg-surface px-2 py-1 text-[11px] text-ink-2 shadow-float"
                >
                  {layers.county === "outages" ? "Customers out now" : "Outage risk"}
                  <span aria-hidden className="inline-flex h-2 w-14 overflow-hidden rounded-[2px]">
                    {[1, 2, 3, 4, 5].map((i) => (
                      <span
                        key={i}
                        className="h-full flex-1"
                        style={{
                          background:
                            layers.county === "outages" ? `var(--map-surge-${6 - i})` : `var(--risk-${i})`,
                        }}
                      />
                    ))}
                  </span>
                </p>
              )}
            </>
          )}
          {full && layers.steps && unplacedNote(data.unplaced) && (
            <p
              role="status"
              data-testid="unplaced-steps"
              className="absolute top-2 right-14 m-0 rounded-md bg-surface px-2 py-1 text-[12px] text-ink-2 shadow-float"
            >
              {unplacedNote(data.unplaced)}
            </p>
          )}
          {layers.county === "outages" && data.outagesFailed && !data.failed && (
            <p
              role="status"
              className="absolute top-2 right-14 m-0 rounded-md bg-surface px-2 py-1 text-[12px] text-muted shadow-float"
            >
              Customers out aren't available.
            </p>
          )}
          {full && layers.surges && data.surgesFailed && !data.failed && (
            <p
              role="status"
              className="absolute top-2 right-14 m-0 rounded-md bg-surface px-2 py-1 text-[12px] text-muted shadow-float"
            >
              Outage surges aren't available.
            </p>
          )}
          {full && observedOn(layers) && data.observationsFailed && !data.failed && (
            <p
              role="status"
              className="absolute top-2 right-14 m-0 rounded-md bg-surface px-2 py-1 text-[12px] text-muted shadow-float"
            >
              Observations aren't available.
            </p>
          )}
          {data.failed && (
            <p
              role="status"
              className="absolute top-2 right-14 m-0 rounded-md bg-surface px-2 py-1 text-[12px] text-muted shadow-float"
            >
              {data.assets.isError ? "Assets aren't available yet." : "No storm track for this advisory."}
            </p>
          )}
        </>
      )}
    </section>
  );
}
