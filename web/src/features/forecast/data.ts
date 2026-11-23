import { useQuery } from "@tanstack/react-query";
import { getJson } from "@/lib/api";
import { useAdvisories } from "../map/data";
import type { CountyFan, CountyForecast, K17Report, PlanDiff, WhatIf } from "./types";

const STALE = 300_000;

/** Customers out at the storm's peak: the sum of the county medians, as the Briefing's forecast counts it. */
export const forecastPeak = (counties: CountyFan[]): number => counties.reduce((t, c) => t + c.q0500, 0);
export const DEFAULT_REPORT = "outage_loso";

export const useCountyForecast = (label: string | null) =>
  useQuery({
    queryKey: ["forecast", "counties", label],
    queryFn: () =>
      getJson<CountyForecast>(
        `/api/forecasts/outages/counties?advisory=${encodeURIComponent(label as string)}`,
      ),
    enabled: label !== null,
    staleTime: STALE,
    retry: false,
  });

/** The first advisory of the storm has nothing earlier to compare with, so it is never asked for. */
export function usePlanDiff(label: string | null) {
  const advisories = useAdvisories();
  const first = [...(advisories.data ?? [])].sort(
    (a, b) => Date.parse(a.issued_utc) - Date.parse(b.issued_utc),
  )[0]?.advisory_label;
  return useQuery({
    queryKey: ["forecast", "plan-diff", label],
    queryFn: () =>
      getJson<PlanDiff>(`/api/forecasts/outages/plan-diff?to=${encodeURIComponent(label as string)}`),
    enabled: label !== null && advisories.isSuccess && label !== first,
    staleTime: STALE,
    retry: false,
  });
}

export const useWhatIf = () =>
  useQuery({
    queryKey: ["forecast", "what-if"],
    queryFn: () => getJson<WhatIf>("/api/whatif"),
    staleTime: STALE,
    retry: false,
  });

export const useEvaluation = (name: string) =>
  useQuery({
    queryKey: ["models", name, "evaluation"],
    queryFn: () => getJson<K17Report>(`/api/models/${encodeURIComponent(name)}/evaluation`),
    staleTime: STALE,
    retry: false,
  });
