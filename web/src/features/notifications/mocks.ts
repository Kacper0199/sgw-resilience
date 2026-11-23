import { HttpResponse, http } from "msw";
import type { Permission, Permissions } from "@/auth/usePermissions";
import { mockState } from "@/mocks/handlers";
import { recordableBy } from "../readiness/mocks";
import type { Notification, NotificationFeed, NotificationRead } from "./useNotifications";

/** Mirrors `sgw.api.permissions` for the seeded personas. */
const GRANTS: Record<string, Permission[]> = {
  ic_01: ["stop_raise", "stop_restore", "mode_raise", "mode_lower"],
  ops_dm_01: ["stop_raise", "mode_raise", "crew_dispatch"],
  ops_dm_02: ["stop_raise", "mode_raise", "crew_dispatch"],
  plan_etr_01: [],
  log_01: ["crew_dispatch"],
  wtr_lead_01: ["stop_raise", "mode_raise"],
  wtr_comp_01: ["stop_restore"],
  exec_01: ["stop_raise", "mode_raise"],
  audit_01: [],
  admin_01: ["mode_raise", "pipeline_run", "agent_run_cancel", "admin"],
  ml_01: ["pipeline_run", "agent_run_cancel"],
};

const NONE: Permissions = {
  stop_raise: false,
  stop_restore: false,
  mode_raise: false,
  mode_lower: false,
  crew_dispatch: false,
  pipeline_run: false,
  agent_run_cancel: false,
  admin: false,
};

export const permissionsFor = (userId: string): Permissions => ({
  ...(Object.fromEntries(
    Object.keys(NONE).map((k) => [k, (GRANTS[userId] ?? []).includes(k as Permission)]),
  ) as unknown as Permissions),
  readiness_record: recordableBy(userId),
});

type Item = Omit<Notification, "read"> & { to: string[] };

const ITEMS: Item[] = [
  {
    notification_id: "waiting:PRP-PS17-FDR2207-PRIO:v2",
    kind: "decision_waiting",
    title: "Decision waiting on you",
    detail: "Keep power to Tallowbranch pump station 17",
    at: "2024-09-27T00:40:00Z",
    href: "/decisions/PRP-PS17-FDR2207-PRIO",
    to: ["ic_01", "wtr_lead_01"],
  },
  {
    notification_id: "deadline:PRP-PS17-FDR2207-PRIO:20240927T0229",
    kind: "deadline_soon",
    title: "Deadline in under 2 hours",
    detail: "Keep power to Tallowbranch pump station 17",
    at: "2024-09-27T02:29:00Z",
    href: "/decisions/PRP-PS17-FDR2207-PRIO",
    to: ["ic_01", "ops_dm_01", "wtr_lead_01"],
  },
  {
    notification_id: "surge:mock7counties",
    kind: "surge_detected",
    title: "Outage surge in 7 counties",
    detail: "Burke, GA; Greene, GA; Oglethorpe, GA and 4 more",
    at: "2024-09-26T14:45:00Z",
    href: "/map",
    to: ["ic_01", "ops_dm_01", "ops_dm_02", "plan_etr_01", "log_01", "exec_01"],
  },
  {
    notification_id: "audit:104",
    kind: "crew_signature_waiting",
    title: "Crew assignment waiting for your signature",
    detail: "CRW-EGRET-0207",
    at: "2024-09-26T15:05:00Z",
    href: "/crews?crew=CRW-EGRET-0207",
    to: ["log_01"],
  },
  {
    notification_id: "audit:51",
    kind: "signature_voided",
    title: "Your signature was voided by a re-plan",
    detail: "Pre-position crews at Sandhill and Millpond yards",
    at: "2024-09-26T15:05:00Z",
    href: "/decisions/PRP-PS17-FDR2207-PRIO",
    to: ["ic_01"],
  },
  {
    notification_id: "audit:12",
    kind: "mode_changed",
    title: "Operating mode: Reduced AI",
    detail: "Gateway latency drill",
    at: "2024-09-26T12:00:00Z",
    href: "/health?tab=safety",
    to: ["ic_01", "ops_dm_01", "wtr_lead_01", "wtr_comp_01", "exec_01", "audit_01", "admin_01", "ml_01"],
  },
];

const reads = new Map<string, Set<string>>();

function feedFor(userId: string): NotificationFeed {
  const seen = reads.get(userId) ?? new Set<string>();
  const items = ITEMS.filter((i) => i.to.includes(userId)).map(
    ({ to: _to, ...i }): Notification => ({ ...i, read: seen.has(i.notification_id) }),
  );
  return { items, unread: items.filter((i) => !i.read).length };
}

const signedOut = () =>
  HttpResponse.json({ error: { code: "UNAUTHENTICATED", message: "sign in first" } }, { status: 401 });

export const handlers = [
  http.get("/api/me/permissions", () =>
    mockState.userId ? HttpResponse.json(permissionsFor(mockState.userId)) : signedOut(),
  ),
  http.get("/api/notifications", () =>
    mockState.userId ? HttpResponse.json(feedFor(mockState.userId)) : signedOut(),
  ),
  http.post("/api/notifications/read", async ({ request }) => {
    const user = mockState.userId;
    if (!user) return signedOut();
    const body = (await request.json()) as NotificationRead;
    const current = feedFor(user).items.map((i) => i.notification_id);
    const seen = reads.get(user) ?? new Set<string>();
    for (const id of body.all ? current : current.filter((i) => body.ids?.includes(i))) seen.add(id);
    reads.set(user, seen);
    return HttpResponse.json(feedFor(user));
  }),
];

export const resetNotificationReads = () => reads.clear();
