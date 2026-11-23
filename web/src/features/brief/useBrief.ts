import { useQuery } from "@tanstack/react-query";
import { briefApi } from "./api";

export const BRIEF_KEY = ["brief"] as const;

export const useBrief = () =>
  useQuery({ queryKey: BRIEF_KEY, queryFn: briefApi.brief, refetchInterval: 60_000 });
