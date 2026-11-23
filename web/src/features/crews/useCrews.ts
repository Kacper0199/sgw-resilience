import { useQuery } from "@tanstack/react-query";
import { crewsApi } from "./api";

export const useCrewList = () => useQuery({ queryKey: ["crews"], queryFn: crewsApi.crews });
export const useCrewPlan = () => useQuery({ queryKey: ["crews", "plan"], queryFn: crewsApi.plan });
export const useDamageQueue = () => useQuery({ queryKey: ["damage", "queue"], queryFn: crewsApi.damage });
export const useWaterAssets = () => useQuery({ queryKey: ["assets", "water"], queryFn: crewsApi.assets });
export const useLadiEvaluation = () =>
  useQuery({ queryKey: ["models", "ladi_reference", "evaluation"], queryFn: crewsApi.ladiEvaluation });
