import { useQuery } from "@tanstack/react-query";
import type { components } from "@/contracts/api.gen";
import { type Asset, api, getJson } from "@/lib/api";

export type EvidenceRecord = components["schemas"]["EvidenceRecord"];

export const useAssets = () =>
  useQuery({ queryKey: ["assets"], queryFn: api.assets, staleTime: 300_000, retry: false });

export const useAssetIndex = (): ReadonlyMap<string, Asset> => {
  const data = useAssets().data;
  return new Map((data ?? []).map((a) => [a.asset_id, a]));
};

export const usePolicies = () =>
  useQuery({ queryKey: ["policies"], queryFn: api.policies, staleTime: 300_000, retry: false });

export const useAudit = (proposalId: string) =>
  useQuery({
    queryKey: ["proposals", proposalId, "audit"],
    queryFn: api.audit,
    select: (events) => events.filter((e) => e.subject === proposalId),
    retry: false,
  });

/** The records a decision rests on, resolved by id: kind, title, source and as-of time. */
export const useEvidence = (proposalId: string) =>
  useQuery({
    queryKey: ["proposals", proposalId, "evidence"],
    queryFn: () => getJson<EvidenceRecord[]>(`/api/proposals/${encodeURIComponent(proposalId)}/evidence`),
    staleTime: 300_000,
    retry: false,
  });
