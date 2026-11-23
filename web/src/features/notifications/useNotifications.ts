import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMe } from "@/auth/useSession";
import type { components } from "@/contracts/api.gen";
import { getJson, post } from "@/lib/api";

export type NotificationFeed = components["schemas"]["NotificationFeed"];
export type Notification = components["schemas"]["Notification"];
export type NotificationRead = components["schemas"]["NotificationRead"];

export const NOTIFICATIONS_KEY = ["notifications"] as const;
const REFRESH_MS = 60_000;

export function useNotifications() {
  const me = useMe().data;
  return useQuery({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: () => getJson<NotificationFeed>("/api/notifications"),
    enabled: !!me,
    refetchInterval: REFRESH_MS,
    retry: false,
  });
}

export const useUnreadCount = (): number => useNotifications().data?.unread ?? 0;

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: NotificationRead) => post<NotificationFeed>("/api/notifications/read", body),
    onSuccess: (feed) => qc.setQueryData(NOTIFICATIONS_KEY, feed),
  });
}
