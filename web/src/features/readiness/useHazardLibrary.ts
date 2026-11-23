import { useQuery } from "@tanstack/react-query";
import { get } from "@/lib/api";
import type { HeatView, WildfireView } from "./hazardTypes";

const FIVE_MINUTES = 300_000;

export const useHeatLibrary = () =>
  useQuery({
    queryKey: ["hazards-library", "heat"],
    queryFn: () => get<HeatView>("/api/hazards/library/heat"),
    staleTime: FIVE_MINUTES,
  });

export const useWildfireLibrary = () =>
  useQuery({
    queryKey: ["hazards-library", "wildfire"],
    queryFn: () => get<WildfireView>("/api/hazards/library/wildfire"),
    staleTime: FIVE_MINUTES,
  });
