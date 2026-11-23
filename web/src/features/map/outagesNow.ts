import { useQuery } from "@tanstack/react-query";
import type { components } from "@/contracts/api.gen";
import { getJson } from "@/lib/api";

export type CountyOutagesNow = components["schemas"]["CountyOutagesNow"];

/** Customers out per county from the outage feed at `asOf`: the hour and source of the Briefing and Forecast totals. */
export const useCountyOutages = (asOf: string | null, enabled: boolean) =>
  useQuery({
    queryKey: ["outages", "counties", asOf],
    queryFn: () =>
      getJson<CountyOutagesNow>(`/api/outages/counties?as_of=${encodeURIComponent(asOf as string)}`),
    enabled: enabled && asOf !== null,
    staleTime: Number.POSITIVE_INFINITY,
    placeholderData: (previous) => previous,
    retry: false,
  });

export const outagesByCounty = (report: CountyOutagesNow | undefined): Map<string, number> =>
  new Map((report?.counties ?? []).map((c) => [c.fips, c.customers_out]));
