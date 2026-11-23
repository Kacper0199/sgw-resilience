import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { afterActionApi } from "./api";

export const AFTER_ACTION_KEY = ["after-action"] as const;

export const useAfterAction = () =>
  useQuery({ queryKey: AFTER_ACTION_KEY, queryFn: afterActionApi.review, retry: false });

export function useVerify() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: afterActionApi.verify,
    onSuccess: () => qc.invalidateQueries({ queryKey: AFTER_ACTION_KEY }),
  });
}

export const useTamperDemo = () => useMutation({ mutationFn: afterActionApi.tamperDemo });
