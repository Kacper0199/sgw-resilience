import { parseAsString, useQueryState } from "nuqs";
import { useEffect, useMemo, useState } from "react";
import { SplitPane } from "@/components/sgw";
import { useScenarioNow } from "@/sse/useScenarioNow";
import { useQueue } from "../decisions/useQueue";
import { advisoryAt, useAdvisories } from "./data";
import type { LayerState } from "./layers";
import MapContainer from "./MapContainer";
import { MapSide } from "./MapSide";
import type { StepStop } from "./Overlays";

export default function MapPage() {
  const [d, setD] = useQueryState("d", parseAsString);
  const [decision, setDecision] = useQueryState("decision", parseAsString);
  const [assetParam, setAssetParam] = useQueryState("asset", parseAsString);
  const [county, setCounty] = useQueryState("county", parseAsString);
  const selected = d ?? decision;
  const setSelected = (id: string | null) => {
    void setD(id);
    if (id === null) void setDecision(null);
  };
  const [picked, setPicked] = useState<string[]>(assetParam ? [assetParam] : []);
  const [step, setStep] = useState<StepStop | null>(null);
  const [layers, setLayers] = useState<LayerState | undefined>(undefined);
  const [at, setAt] = useQueryState("at", parseAsString);
  const queue = useQueue();
  const now = useScenarioNow();
  const advisories = useAdvisories();
  const current = advisoryAt(advisories.data ?? [], now);
  const chosen = advisories.data?.find((a) => a.issued_utc === at)?.advisory_label;
  const label = chosen ?? current?.advisory_label ?? null;
  const asOf =
    advisories.data?.find((a) => a.advisory_label === label)?.issued_utc ?? current?.issued_utc ?? null;
  const summary = queue.items.find((i) => i.summary.proposal_id === selected)?.summary;
  const cards = useMemo(() => queue.items.flatMap((i) => (i.card ? [i.card] : [])), [queue.items]);
  const pickedSet = useMemo(() => new Set(picked), [picked]);

  useEffect(() => {
    if (assetParam) setPicked([assetParam]);
  }, [assetParam]);

  const clear = () => {
    setSelected(null);
    void setAssetParam(null);
    void setCounty(null);
    setPicked([]);
    setStep(null);
  };

  return (
    <div className="flex h-full min-h-[560px] flex-col max-[1099px]:h-auto">
      <h1 className="sr-only">Map</h1>
      <div className="min-h-0 flex-1">
        <SplitPane
          id="map"
          scrollMain={false}
          mainMinSize={360}
          end={{
            label: "Resize map panel",
            scrollRegion: "map-panel",
            defaultSize: "30%",
            minSize: 260,
            maxSize: "55%",
            content: (
              <div className="min-h-full bg-surface">
                <MapSide
                  decision={summary ? { proposalId: summary.proposal_id, title: summary.title } : null}
                  step={step}
                  picked={picked}
                  cards={cards}
                  now={now ?? new Date().toISOString()}
                  asOf={asOf}
                  onClosePicked={() => {
                    void setAssetParam(null);
                    setPicked([]);
                    setStep(null);
                  }}
                />
              </div>
            ),
          }}
        >
          <div className="h-full min-h-[520px] min-w-0">
            <MapContainer
              variant="full"
              layers={layers}
              onLayersChange={setLayers}
              advisoryLabel={label}
              onAdvisoryChange={(next) =>
                void setAt(
                  next === current?.advisory_label
                    ? null
                    : (advisories.data?.find((a) => a.advisory_label === next)?.issued_utc ?? null),
                )
              }
              selectedProposalId={selected}
              selectedAssetIds={picked.length > 0 ? pickedSet : undefined}
              activeStepKey={step?.key ?? null}
              onSelectProposal={setSelected}
              focusCounty={county}
              onAssetsPicked={(ids) => {
                void setAssetParam(null);
                setPicked(ids);
                setStep(null);
              }}
              onStepPicked={(s) => {
                setStep(s);
                setPicked([s.assetId]);
              }}
              onClearSelection={clear}
            />
          </div>
        </SplitPane>
      </div>
    </div>
  );
}
