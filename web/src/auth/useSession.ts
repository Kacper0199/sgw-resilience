import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type AuthConfig, api, hasSessionHint, type Me } from "@/lib/api";
import { resetSession } from "@/lib/sessionReset";

export const ME_KEY = ["me"] as const;

export function useMe() {
  return useQuery<Me | null>({
    queryKey: ME_KEY,
    queryFn: async () => {
      if (!hasSessionHint()) return null;
      try {
        return await api.me();
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return null;
        throw err;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { user_id: string; password: string }) => api.login(v.user_id, v.password),
    onSuccess: (me) => {
      resetSession();
      qc.clear();
      qc.setQueryData(ME_KEY, me);
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.logout,
    onSettled: () => {
      resetSession();
      qc.clear();
      qc.setQueryData(ME_KEY, null);
    },
  });
}

export function useStepUp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (password: string) => api.stepUp(password),
    onSuccess: (me) => qc.setQueryData(ME_KEY, me),
  });
}

/** Demo mode decides whether the persona picker is offered. Any failure means "not demo": no picker. */
export function useAuthConfig() {
  return useQuery<AuthConfig>({
    queryKey: ["auth-config"],
    queryFn: async () => {
      try {
        return await api.authConfig();
      } catch {
        return { demo_mode: false };
      }
    },
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
}
