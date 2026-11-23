import type { components, operations } from "@/contracts/api.gen";

type Json<R> = R extends { content: { "application/json": infer B } } ? B : never;
type Ok<Op extends keyof operations> = operations[Op]["responses"] extends { 200: infer R } ? Json<R> : never;
type Created<Op extends keyof operations> = operations[Op]["responses"] extends { 201: infer R }
  ? Json<R>
  : never;

export type Me = components["schemas"]["Me"];
export type ScenarioState = components["schemas"]["ScenarioState"];
export type ProposalSummary = components["schemas"]["ProposalSummary"];
export type MissedDecisionCase = components["schemas"]["MissedDecisionCase"];
export type ProposalCard = components["schemas"]["ProposalCard"];
export type ApprovalRequest = components["schemas"]["ApprovalRequest"];
export type ApprovalResponse = components["schemas"]["ApprovalResponse"];
export type Region = components["schemas"]["Region"];
export type Asset = components["schemas"]["Asset"];
export type ClockWaterfall = components["schemas"]["ClockWaterfall"];
export type BreakGlassRequest = components["schemas"]["BreakGlassRequest"];
export type AuditEvent = components["schemas"]["AuditEventOut"];
export type PolicyParam = components["schemas"]["PolicyParam"];
export type Envelope = components["schemas"]["Envelope"];

/** `GET /api/auth/config`; replaced by the generated type when the backend contract lands. */
export interface AuthConfig {
  demo_mode: boolean;
  /** The public demo password, sent only in demo mode when every account really uses it. */
  demo_password?: string | null;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly body: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

function csrfToken(): string | undefined {
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith("sgw_csrf="))
    ?.slice("sgw_csrf=".length);
}

/** The CSRF cookie is set at login and readable by the page, so its absence means there is no session to probe. */
export const hasSessionHint = (): boolean => csrfToken() !== undefined;

export type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler | null = null;
/** For callers outside `request` (the event stream) that learn the session ended. */
export const notifyUnauthorized = (): void => onUnauthorized?.();

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE.has(method)) {
    const csrf = csrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  const res = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    cache: "no-cache",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let parsed: unknown;
  try {
    parsed = text ? JSON.parse(text) : undefined;
  } catch {
    throw new ApiError(
      res.status,
      `HTTP_${res.status}`,
      res.ok ? "Something went wrong. Try again." : res.statusText,
      text,
    );
  }
  if (!res.ok) {
    const err = (parsed as { error?: { code?: string; message?: string } } | undefined)?.error;
    const code = err?.code ?? `HTTP_${res.status}`;
    // A wrong password on step-up is a 401 too, but the session is still valid.
    if (res.status === 401 && path !== "/api/auth/login" && code !== "STEP_UP_FAILED") onUnauthorized?.();
    throw new ApiError(res.status, code, err?.message ?? res.statusText, parsed);
  }
  return parsed as T;
}

export const get = <T>(path: string) => request<T>("GET", path);
/** Typed GET for endpoints the generated contract does not describe yet. */
export const getJson = get;
export const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body);

export const api = {
  authConfig: () => get<AuthConfig>("/api/auth/config"),
  login: (user_id: string, password: string) => post<Ok<"login">>("/api/auth/login", { user_id, password }),
  logout: () => post<void>("/api/auth/logout"),
  stepUp: (password: string) => post<Ok<"stepUp">>("/api/auth/step-up", { password }),
  me: () => get<Ok<"getMe">>("/api/me"),
  scenario: () => get<Ok<"getScenario">>("/api/scenario"),
  regions: () => get<Ok<"listRegions">>("/api/regions"),
  assets: () => get<Ok<"listAssets">>("/api/assets"),
  proposals: () => get<Ok<"listProposals">>("/api/proposals"),
  missedCases: () => get<Ok<"listMissedDecisionCases">>("/api/decision-cases/missed"),
  proposal: (id: string) => get<Ok<"getProposal">>(`/api/proposals/${encodeURIComponent(id)}`),
  clock: (id: string) => get<Ok<"getClock">>(`/api/proposals/${encodeURIComponent(id)}/clock`),
  approve: (id: string, body: ApprovalRequest) =>
    post<Ok<"approveProposal">>(`/api/proposals/${encodeURIComponent(id)}/approvals`, body),
  breakGlass: (id: string, body: BreakGlassRequest) =>
    post<Ok<"breakGlass">>(`/api/proposals/${encodeURIComponent(id)}/break-glass`, body),
  cosign: (id: string) => post<Ok<"cosignBreakGlass">>(`/api/proposals/${encodeURIComponent(id)}/cosign`),
  audit: () => get<Ok<"listAudit">>("/api/audit"),
  policies: () => get<Ok<"listPolicies">>("/api/policies"),
  createProposal: (body: components["schemas"]["ProposalCreate"]) =>
    post<Created<"createProposal">>("/api/proposals", body),
};
