import { useQuery } from "@tanstack/react-query";
import { get } from "@/lib/api";
import type { ReadinessItem } from "./types";

export const useReadiness = () =>
  useQuery({
    queryKey: ["readiness"],
    queryFn: () => get<ReadinessItem[]>("/api/readiness"),
    staleTime: 30_000,
  });
