import { useQuery } from "@tanstack/react-query";
import { api, getJson } from "@/lib/api";
import { isPack } from "@/lib/scenarios";
import { useScenario } from "@/sse/useScenarioNow";
import type { AdvisoryHazard, AdvisoryIndexItem, RiskResponse } from "./types";

const STALE = 300_000;

export const useAssets = () =>
  useQuery({ queryKey: ["assets"], queryFn: api.assets, staleTime: STALE, retry: false });

export const useRegions = () =>
  useQuery({ queryKey: ["regions"], queryFn: api.regions, staleTime: STALE, retry: false });

export const useAdvisories = () =>
  useQuery({
    queryKey: ["hazard", "advisories"],
    queryFn: () => getJson<AdvisoryIndexItem[]>("/api/hazard/advisories"),
    staleTime: STALE,
    retry: false,
  });

export const useAdvisoryHazard = (label: string | null) =>
  useQuery({
    queryKey: ["hazard", "advisories", label],
    queryFn: () => getJson<AdvisoryHazard>(`/api/hazard/advisories/${encodeURIComponent(label as string)}`),
    enabled: label !== null,
    staleTime: STALE,
    retry: false,
  });

/** County outage risk at an advisory; never asked for a scripted exercise pack, which has no risk model. */
export function useCountyRisk(asOf: string | null) {
  const scenario = useScenario().data?.scenario;
  const modelled = scenario !== undefined && !isPack(scenario);
  return useQuery({
    queryKey: ["risk", "county", asOf],
    queryFn: () =>
      getJson<RiskResponse>(`/api/risk?level=county&as_of=${encodeURIComponent(asOf as string)}`),
    enabled: asOf !== null && modelled,
    staleTime: STALE,
    retry: false,
  });
}

/** The advisory in force at a scenario time: the latest one issued at or before it, else the first. */
export function advisoryAt(advisories: AdvisoryIndexItem[], nowIso: string | null): AdvisoryIndexItem | null {
  if (advisories.length === 0) return null;
  const sorted = [...advisories].sort((a, b) => Date.parse(a.issued_utc) - Date.parse(b.issued_utc));
  const now = nowIso ? Date.parse(nowIso) : Number.NaN;
  const issued = sorted.filter((a) => Date.parse(a.issued_utc) <= now);
  return issued.length > 0
    ? (issued[issued.length - 1] as AdvisoryIndexItem)
    : (sorted[0] as AdvisoryIndexItem);
}
