import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import { useMe } from "@/auth/useSession";
import { api, type Me, type ProposalCard, type ProposalSummary } from "@/lib/api";
import { useScenario } from "@/sse/useScenarioNow";
import { observeClocks, observeScenarioTime } from "./clockShifts";
import { OPEN_STATES } from "./severity";
import { observeVersions } from "./voidedApprovals";

export const useProposals = () => useQuery({ queryKey: ["proposals"], queryFn: api.proposals });

/** Decisions whose deadline passed with no proposal, read again each scenario minute: Closed lists them as missed. */
export const useMissedCases = (now: string) =>
  useQuery({
    queryKey: ["decision-cases", "missed", now.slice(0, 16)],
    queryFn: api.missedCases,
    placeholderData: keepPreviousData,
  });

/** An open decision's id only once the decision list holds it: after another database is loaded, an id from
 * the old one is never read (`gone` once the fresh list is in and lacks it). */
export function useListed(id: string | null): { id: string | null; gone: boolean } {
  const proposals = useProposals();
  if (id === null || proposals.isError) return { id, gone: false };
  const listed = proposals.data?.some((p) => p.proposal_id === id) ?? false;
  return { id: listed ? id : null, gone: !listed && !proposals.isFetching && proposals.data !== undefined };
}

export function useCard(id: string | null) {
  return useQuery({
    queryKey: ["proposals", id],
    queryFn: () => api.proposal(id as string),
    enabled: id !== null,
  });
}

export type SignBlock = "not_required" | "already_signed" | "closed" | null;

/** Why this person cannot sign, or null when they can. */
export function signBlock(
  me: Me,
  p: Pick<ProposalSummary, "state" | "functions_required" | "approvals">,
): SignBlock {
  if (!OPEN_STATES.has(p.state)) return "closed";
  if (!p.functions_required.includes(me.function)) return "not_required";
  if (p.approvals.some((a) => a.function === me.function && a.decision !== "reject")) return "already_signed";
  return null;
}

export function useWaitingOnMe(): number {
  const me = useMe().data;
  const proposals = useProposals().data;
  if (!me || !proposals) return 0;
  return proposals.filter((p) => signBlock(me, p) === null).length;
}

export interface QueueItem {
  summary: ProposalSummary;
  card: ProposalCard | undefined;
}

export function useQueue() {
  const proposals = useProposals();
  const cards = useQueries({
    queries: (proposals.data ?? []).map((p) => ({
      queryKey: ["proposals", p.proposal_id],
      queryFn: () => api.proposal(p.proposal_id),
    })),
    combine: (results) => results.map((r) => r.data),
  });
  const items = useMemo<QueueItem[]>(
    () => (proposals.data ?? []).map((summary, i) => ({ summary, card: cards[i] })),
    [proposals.data, cards],
  );
  const scenarioTime = useScenario().data?.scenario_time;
  useEffect(() => observeScenarioTime(scenarioTime), [scenarioTime]);
  useEffect(() => {
    observeClocks(items);
    observeVersions(items);
  }, [items]);
  return { items, isPending: proposals.isPending, error: proposals.error, refetch: proposals.refetch };
}
