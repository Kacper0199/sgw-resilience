import { useQuery } from "@tanstack/react-query";
import type { components } from "@/contracts/api.gen";
import { getJson } from "@/lib/api";
import { useMe } from "./useSession";

export type Permissions = components["schemas"]["Permissions"];
export type Permission = Exclude<keyof Permissions, "readiness_record">;

/** What the signed-in person may do, from the rules the API enforces (`GET /api/me/permissions`). */
export function usePermissions() {
  const me = useMe().data;
  return useQuery({
    queryKey: ["me", "permissions", me?.user_id ?? null],
    queryFn: () => getJson<Permissions>("/api/me/permissions"),
    enabled: !!me,
    staleTime: 60_000,
    retry: false,
  });
}

/** False while loading or on error, so a control the API may refuse is never offered by mistake. */
export const useCan = (permission: Permission): boolean => usePermissions().data?.[permission] === true;
