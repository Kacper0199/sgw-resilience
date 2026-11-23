import { useQueries, useQuery } from "@tanstack/react-query";
import { api, type ProposalCard } from "@/lib/api";
import { waterApi } from "./api";
import { noticeLifecycle, noticesInOrder, type ZoneNotice } from "./lifecycle";

const OPEN = new Set(["proposed", "in_review", "escalated"]);

export const useZones = () => useQuery({ queryKey: ["water", "zones"], queryFn: waterApi.zones });
export const useAdvisories = () =>
  useQuery({ queryKey: ["water", "advisories"], queryFn: waterApi.advisories });
export const useRules = () => useQuery({ queryKey: ["water", "rules"], queryFn: waterApi.rules });
export const useAnomalies = () => useQuery({ queryKey: ["anomalies"], queryFn: waterApi.anomalies });
export const useAnomalyEvaluation = () =>
  useQuery({ queryKey: ["models", "anomaly_a7_a8", "evaluation"], queryFn: waterApi.anomalyEvaluation });
export const usePolicies = () => useQuery({ queryKey: ["policies"], queryFn: waterApi.policies });

/** Open water decisions (any decision the water function signs, such as the restoration order) with their cards; shares the cache keys of the Decisions queue. */
export function useWaterCases() {
  const proposals = useQuery({ queryKey: ["proposals"], queryFn: api.proposals });
  const cards = useQueries({
    queries: (proposals.data ?? []).map((p) => ({
      queryKey: ["proposals", p.proposal_id],
      queryFn: () => api.proposal(p.proposal_id),
    })),
  });
  const everyWater = cards
    .map((q) => q.data)
    .filter(
      (c): c is ProposalCard =>
        c !== undefined && (c.case.domain === "water" || c.functions_required.includes("water_operations")),
    );
  const water = everyWater.filter((c) => OPEN.has(c.state));
  return {
    cards: water,
    allCards: everyWater,
    isPending: proposals.isPending || cards.some((q) => q.isPending),
    error: proposals.error,
  };
}

/** Every zone with a boil-water notice in play, most urgent first; zones above the minimum with no notice are left out. */
export function useZoneNotices(): { notices: ZoneNotice[]; isPending: boolean; error: unknown } {
  const zones = useZones();
  const adv = useAdvisories();
  const cases = useWaterCases();
  const notices = noticesInOrder(
    (zones.data ?? []).flatMap((z) => {
      const n = noticeLifecycle(z, adv.data?.advisories ?? [], cases.allCards);
      return n ? [n] : [];
    }),
  );
  return {
    notices,
    isPending: zones.isPending || adv.isPending || cases.isPending,
    error: zones.error ?? adv.error ?? cases.error,
  };
}

/** Critical-path cases first in prerequisite order (ties by decide-by), then the rest by decide-by. */
export function orderCases(cards: ProposalCard[]): { chain: ProposalCard[]; others: ProposalCard[] } {
  const byCase = new Map(cards.map((c) => [c.decision_case_id, c]));
  const onPath = cards.filter((c) => c.case.on_critical_path);
  const done = new Set<string>();
  const chain: ProposalCard[] = [];
  const rank = (a: ProposalCard, b: ProposalCard) =>
    Date.parse(a.effective_decide_by_utc) - Date.parse(b.effective_decide_by_utc);
  while (chain.length < onPath.length) {
    const ready = onPath
      .filter((c) => !done.has(c.decision_case_id))
      .filter((c) =>
        (c.case.prerequisite_ids ?? []).every((id) => done.has(id) || !byCase.get(id)?.case.on_critical_path),
      )
      .sort(rank);
    const next = ready[0] ?? onPath.filter((c) => !done.has(c.decision_case_id)).sort(rank)[0];
    if (!next) break;
    done.add(next.decision_case_id);
    chain.push(next);
  }
  const others = cards.filter((c) => !c.case.on_critical_path).sort(rank);
  return { chain, others };
}
