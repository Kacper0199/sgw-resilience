import { useMemo } from "react";
import { decisionTitle } from "@/features/decisions/actionTypes";
import type { ProposalCard } from "@/lib/api";
import { ViewDecisionLink } from "../decisions/DecisionLink";
import { AssetPanel } from "./AssetPanel";
import { useAssets } from "./data";
import { Lifelines } from "./Lifelines";
import { type StepStop, stepName } from "./Overlays";

interface Props {
  decision: { proposalId: string; title: string } | null;
  step: StepStop | null;
  picked: string[];
  cards: ProposalCard[];
  now: string;
  asOf: string | null;
  onClosePicked: () => void;
}

/** The panel beside the map: the selected decision and step, the asset under the last click, else the lifelines. */
export function MapSide({ decision, step, picked, cards, now, asOf, onClosePicked }: Props) {
  const assets = useAssets();
  const pickedAssets = useMemo(
    () => (assets.data ?? []).filter((a) => picked.includes(a.asset_id)),
    [assets.data, picked],
  );
  return (
    <>
      {decision && (
        <div data-testid="map-selection" className="flex flex-col gap-1 border-b border-hair px-5 py-3">
          <div className="flex h-6 items-center justify-between">
            <span className="text-[12px] font-semibold text-muted">Selected decision</span>
            <ViewDecisionLink proposalId={decision.proposalId} />
          </div>
          <span className="text-[14px] leading-5 font-medium">{decisionTitle(decision.title)}</span>
          {step && (
            <span data-testid="map-step" className="text-[12px] text-ink-2">
              Step {step.number}
              {step.title !== decision.title ? `: ${stepName(step)}` : ""}
            </span>
          )}
        </div>
      )}
      {pickedAssets.length > 0 ? (
        <AssetPanel assets={pickedAssets} cards={cards} now={now} onClose={onClosePicked} />
      ) : (
        <Lifelines asOf={asOf} />
      )}
    </>
  );
}
