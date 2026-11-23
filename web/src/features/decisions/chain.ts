import { minutesUntil } from "@/lib/time";
import { OPEN_STATES } from "./severity";
import { type QueueItem, useQueue } from "./useQueue";

export interface ChainLink {
  /** Step number of the prerequisite this link comes from. */
  from: number;
  /** Minutes to spare before the prerequisite has to be decided for this step to keep its own decide-by; null once it is decided. */
  slackMin: number | null;
}

export interface ChainStep {
  n: number;
  item: QueueItem;
  caseId: string;
  /** One link per prerequisite of this step that is in the chain. */
  incoming: ChainLink[];
}

export interface Chain {
  steps: ChainStep[];
  blockedBy: QueueItem[];
  blocks: QueueItem[];
}

const caseOf = (i: QueueItem) => i.summary.decision_case_id;

/** Prerequisites per decision, from the card, the payload's own `blocked_by`, and the `blocks` of the other decisions. */
function prerequisiteMap(items: QueueItem[]): Map<string, string[]> {
  const map = new Map<string, Set<string>>(items.map((i) => [caseOf(i), new Set<string>()]));
  for (const i of items) {
    const c = i.card?.case;
    for (const p of [...(c?.prerequisite_ids ?? []), ...(c?.blocked_by ?? [])]) map.get(caseOf(i))?.add(p);
    for (const b of c?.blocks ?? []) map.get(b)?.add(caseOf(i));
  }
  return new Map([...map].map(([k, v]) => [k, [...v]]));
}

/**
 * The numbered chain around one decision: prerequisites first. Every prerequisite of a step is a link into it;
 * its slack is the time the step's effective decide-by leaves after the prerequisite's lead time, counted from now.
 */
export function buildChain(items: QueueItem[], selectedId: string | null, now: string): Chain {
  const byCase = new Map(items.map((i) => [caseOf(i), i]));
  const pre = prerequisiteMap(items);
  const prereqs = (i: QueueItem) => pre.get(caseOf(i)) ?? [];
  const selected = items.find((i) => i.summary.proposal_id === selectedId);
  if (!selected) return { steps: [], blockedBy: [], blocks: [] };

  const blocks = items.filter((i) => prereqs(i).includes(caseOf(selected)));
  const blockedBy = prereqs(selected)
    .map((c) => byCase.get(c))
    .filter((i): i is QueueItem => Boolean(i));

  const component = new Set<string>([caseOf(selected)]);
  const queue = [caseOf(selected)];
  while (queue.length) {
    const cur = byCase.get(queue.pop() as string);
    if (!cur) continue;
    const neighbours = [
      ...prereqs(cur),
      ...items.filter((i) => prereqs(i).includes(caseOf(cur))).map(caseOf),
    ];
    for (const c of neighbours) {
      if (byCase.has(c) && !component.has(c)) {
        component.add(c);
        queue.push(c);
      }
    }
  }

  const nodes = [...component].map((c) => byCase.get(c) as QueueItem);
  const ordered: QueueItem[] = [];
  const placed = new Set<string>();
  const place = (i: QueueItem) => {
    if (placed.has(caseOf(i))) return;
    placed.add(caseOf(i));
    for (const p of prereqs(i)) {
      const dep = byCase.get(p);
      if (dep && component.has(p)) place(dep);
    }
    ordered.push(i);
  };
  const order = (i: QueueItem) => i.card?.case.chain_order ?? Number.POSITIVE_INFINITY;
  for (const i of nodes.sort(
    (a, b) =>
      order(a) - order(b) ||
      Date.parse(a.summary.effective_decide_by_utc) - Date.parse(b.summary.effective_decide_by_utc),
  )) {
    place(i);
  }

  const numberOf = new Map(ordered.map((item, idx) => [caseOf(item), idx + 1]));
  const steps = ordered.map((item, idx): ChainStep => {
    const incoming = prereqs(item).flatMap((dep): ChainLink[] => {
      const from = byCase.get(dep);
      const fromN = numberOf.get(dep);
      if (!from || fromN === undefined) return [];
      const open = OPEN_STATES.has(from.summary.state);
      const lead = from.card?.case.clock.action_lead_time_min ?? 0;
      return [
        {
          from: fromN,
          slackMin: open ? minutesUntil(item.summary.effective_decide_by_utc, now) - lead : null,
        },
      ];
    });
    return { n: idx + 1, item, caseId: caseOf(item), incoming };
  });
  return { steps: steps.length > 1 ? steps : [], blockedBy, blocks };
}

/** Chain of the selected decision for the Path tab and for the map (numbered markers on the chain's assets). */
export function useCriticalChain(selectedProposalId: string | null, now: string): Chain {
  const { items } = useQueue();
  return buildChain(items, selectedProposalId, now);
}
