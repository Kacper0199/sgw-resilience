import type { components } from "@/contracts/api.gen";

export type AdminUser = components["schemas"]["Me"];
export type UserRights = components["schemas"]["UserApprovalRights"];
export type ApprovalRight = components["schemas"]["ApprovalRight"];
export type AiConfig = components["schemas"]["AiConfig"];
export type AiNode = components["schemas"]["AiNodeConfig"];
export type ApiToken = components["schemas"]["ApiTokenOut"];
export type PolicyParam = components["schemas"]["PolicyParam"];
export type ActionType = components["schemas"]["ActionType"];

export interface WebhookSubscription {
  subscription_id: string;
  token_id: string;
  host: string;
  event_types: string[];
  state: "active" | "disabled";
  disabled_reason: string | null;
  created_at: string;
  last_delivery_at: string | null;
  counts: { delivered: number; pending: number; failed: number };
}

export interface WebhookDelivery {
  delivery_id: string;
  subscription_id: string;
  event_type: string;
  status: "delivered" | "pending" | "failed";
  attempts: number;
  last_error: string | null;
  created_at: string;
  delivered_at: string | null;
}

/** `GET /api/admin/integrations`: token metadata (never secrets or hashes), subscriptions by host, latest deliveries. */
export interface Integrations {
  tokens: ApiToken[];
  subscriptions: WebhookSubscription[];
  deliveries: WebhookDelivery[];
}

export type ApiActivity = components["schemas"]["ApiActivity"];
export type RouteTiming = components["schemas"]["RouteTiming"];

/** `GET /api/admin/system`: the API's own request metrics, and Grafana's address while the optional `obs` profile answers. */
export interface SystemInfo {
  obs_profile_up: boolean;
  grafana_url: string | null;
  api?: ApiActivity | null;
}
