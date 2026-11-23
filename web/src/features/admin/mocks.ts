import { delay, HttpResponse, http } from "msw";
import aiConfig from "./mocks/ai-config.json";
import rights from "./mocks/rights.json";
import users from "./mocks/users.json";
import type { AiConfig, Integrations, SystemInfo, UserRights } from "./types";

const OBS_KEY = "sgw.mock.obs_up";

export const integrations: Integrations = {
  tokens: [
    {
      token_id: "itk3f9a1c",
      name: "County emergency office feed",
      scopes: ["decisions:read", "clocks:read"],
      created_by: "admin_01",
      created_at: "2026-11-18T14:02:00Z",
      expires_at: "2027-02-16T14:02:00Z",
      revoked_at: null,
      last_used_at: "2026-11-20T13:41:12Z",
    },
    {
      token_id: "itk77b0d2",
      name: "Regulator read-only pilot",
      scopes: ["decisions:read", "commitments:read", "webhooks:manage"],
      created_by: "admin_01",
      created_at: "2026-11-19T09:30:00Z",
      expires_at: "2027-02-17T09:30:00Z",
      revoked_at: null,
      last_used_at: null,
    },
    {
      token_id: "itk0c41e8",
      name: "Retired dashboard export",
      scopes: ["decisions:read"],
      created_by: "admin_01",
      created_at: "2026-10-02T10:00:00Z",
      expires_at: "2027-01-02T10:00:00Z",
      revoked_at: "2026-11-12T16:20:00Z",
      last_used_at: "2026-11-12T11:05:00Z",
    },
  ],
  subscriptions: [
    {
      subscription_id: "whs_91c2e4",
      token_id: "itk3f9a1c",
      host: "alerts.aiken-county.example",
      event_types: ["decision.approved", "decision.created"],
      state: "active",
      disabled_reason: null,
      created_at: "2026-11-18T14:10:00Z",
      last_delivery_at: "2026-11-20T13:41:15Z",
      counts: { delivered: 42, pending: 0, failed: 0 },
    },
    {
      subscription_id: "whs_5a07b3",
      token_id: "itk77b0d2",
      host: "intake.psc-pilot.example",
      event_types: ["decision.approved", "commitment.missed"],
      state: "disabled",
      disabled_reason: "The receiver answered 410 Gone",
      created_at: "2026-11-19T09:40:00Z",
      last_delivery_at: "2026-11-19T22:16:03Z",
      counts: { delivered: 7, pending: 0, failed: 2 },
    },
  ],
  deliveries: [
    {
      delivery_id: "whd_6b14c9",
      subscription_id: "whs_91c2e4",
      event_type: "decision.approved",
      status: "delivered",
      attempts: 1,
      last_error: null,
      created_at: "2026-11-20T13:41:12Z",
      delivered_at: "2026-11-20T13:41:15Z",
    },
    {
      delivery_id: "whd_2e88a0",
      subscription_id: "whs_91c2e4",
      event_type: "decision.created",
      status: "delivered",
      attempts: 2,
      last_error: null,
      created_at: "2026-11-20T11:02:40Z",
      delivered_at: "2026-11-20T11:03:02Z",
    },
    {
      delivery_id: "whd_f0d3b7",
      subscription_id: "whs_5a07b3",
      event_type: "commitment.missed",
      status: "failed",
      attempts: 8,
      last_error: "Receiver answered 410 Gone",
      created_at: "2026-11-19T22:00:11Z",
      delivered_at: null,
    },
  ],
};

const obsUp = (): boolean => typeof sessionStorage !== "undefined" && sessionStorage.getItem(OBS_KEY) === "1";

export const system = (): SystemInfo => ({
  obs_profile_up: obsUp(),
  grafana_url: obsUp() ? "http://127.0.0.1:3001/" : null,
  api: {
    requests: 4812,
    server_errors: 3,
    window: 2000,
    typical_ms: 14,
    slow_ms: 182,
    slowest: [
      { route: "/api/forecasts/outages/plan-diff", requests: 41, typical_ms: 120, slow_ms: 640 },
      { route: "/api/crews/plan", requests: 88, typical_ms: 64, slow_ms: 310 },
      { route: "/v1/decisions", requests: 236, typical_ms: 22, slow_ms: 95 },
      { route: "/api/water/zones", requests: 112, typical_ms: 18, slow_ms: 71 },
      { route: "/api/me", requests: 402, typical_ms: 3, slow_ms: 9 },
    ],
  },
});

export const handlers = [
  http.get("/api/admin/users", () => HttpResponse.json(users)),
  http.get("/api/admin/approval-rights", () => HttpResponse.json(rights as UserRights[])),
  http.get("/api/admin/ai-config", () => HttpResponse.json(aiConfig as AiConfig)),
  http.get("/api/admin/integrations", async () => {
    await delay(30);
    return HttpResponse.json(integrations);
  }),
  http.get("/api/admin/system", () => HttpResponse.json(system())),
];
