import type { Asset, ProposalCard } from "@/lib/api";
import { assetLabel } from "@/lib/names";
import { buildChain as buildQueueChain } from "../decisions/chain";
import { caseChainOf } from "../decisions/ui";
import type { QueueItem } from "../decisions/useQueue";

export interface SequenceStep {
  number: number;
  caseId: string;
  title: string;
  /** Assets where the step happens, from the chain read model; for a step without a proposal or with vehicle targets. */
  placeIds?: string[];
}

const DESTINATION_PARAMS = ["destination_id", "facility_id"] as const;

/** Where a decision happens: the destination a vehicle is sent to first, then the assets it targets. */
export function placeIdsOf(card: Pick<ProposalCard, "target_ids" | "params">): string[] {
  const params = card.params as Record<string, unknown> | undefined;
  const destinations = DESTINATION_PARAMS.flatMap((k) =>
    typeof params?.[k] === "string" ? [params[k]] : [],
  );
  return [...new Set([...(destinations as string[]), ...card.target_ids])];
}

export interface ChainStop {
  /** Unique per marker: one step can have several assets. */
  key: string;
  /** The step number in the decision's Sequence tab. */
  number: number;
  assetId: string;
  assetName: string;
  caseId: string;
  title: string;
  /** The step has more than one marker, so its name needs the asset to tell them apart. */
  repeated: boolean;
}

/** The Sequence tab's steps for the selected decision: the case's own chain when it has one, else the queue chain. */
export function sequenceOf(selectedId: string | null, items: QueueItem[], now: string): SequenceStep[] {
  const selected = items.find((i) => i.summary.proposal_id === selectedId);
  if (!selected) return [];
  const own = selected.card ? caseChainOf(selected.card) : undefined;
  if (own) {
    return [...own]
      .sort((a, b) => a.order - b.order)
      .map((s) => ({
        number: s.order,
        caseId: s.decision_case_id,
        title: s.title,
        placeIds: s.place_ids ?? [],
      }));
  }
  return buildQueueChain(items, selectedId, now).steps.map((s) => ({
    number: s.n,
    caseId: s.caseId,
    title: s.item.summary.title,
  }));
}

/**
 * One marker per asset a step targets, numbered and named as in the Sequence tab. An asset keeps the first step that
 * targets it; a step whose assets are all taken still gets a marker, on its first one, so every step can be found.
 */
export function buildStops(sequence: SequenceStep[], cards: ProposalCard[], assets: Asset[]): ChainStop[] {
  const byId = new Map(assets.map((a) => [a.asset_id, a]));
  const byCase = new Map(cards.map((c) => [c.decision_case_id, c]));
  const used = new Set<string>();
  const stops: ChainStop[] = [];
  for (const step of sequence) {
    const card = byCase.get(step.caseId);
    const placed = [...new Set([...(card ? placeIdsOf(card) : []), ...(step.placeIds ?? [])])].filter((id) =>
      byId.has(id),
    );
    const fresh = placed.filter((id) => !used.has(id));
    const own = fresh.length > 0 ? fresh : placed.slice(0, 1);
    for (const id of own) used.add(id);
    for (const id of own) {
      const asset = byId.get(id);
      stops.push({
        key: `${step.number}:${id}`,
        number: step.number,
        assetId: id,
        assetName: asset ? assetLabel(asset) : id,
        caseId: step.caseId,
        title: step.title,
        repeated: own.length > 1,
      });
    }
  }
  return stops;
}

/** The steps of the sequence that have no marker because none of their targets has a place on the map. */
export function unplacedSteps(sequence: SequenceStep[], stops: Pick<ChainStop, "number">[]): SequenceStep[] {
  const placed = new Set(stops.map((s) => s.number));
  return sequence.length > 1 ? sequence.filter((s) => !placed.has(s.number)) : [];
}

/** "Step 2 has no place on the map", or null when every step has one. */
export function unplacedNote(steps: Pick<SequenceStep, "number">[]): string | null {
  const numbers = [...new Set(steps.map((s) => s.number))].sort((a, b) => a - b);
  if (numbers.length === 0) return null;
  if (numbers.length === 1) return `Step ${numbers[0]} has no place on the map`;
  const last = numbers[numbers.length - 1];
  return `Steps ${numbers.slice(0, -1).join(", ")} and ${last} have no place on the map`;
}

/** The most urgent open decision that targets any of the assets under a click. */
export function proposalForAssets(assetIds: string[], cards: ProposalCard[]): string | null {
  const hits = cards.filter((c) => placeIdsOf(c).some((t) => assetIds.includes(t)));
  hits.sort((a, b) => Date.parse(a.effective_decide_by_utc) - Date.parse(b.effective_decide_by_utc));
  return hits[0]?.proposal_id ?? null;
}
