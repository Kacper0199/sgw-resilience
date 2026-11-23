import { ApiError, get, post } from "@/lib/api";
import type { AfterAction, AuditVerifyResult, TamperDemo } from "./types";

export const afterActionApi = {
  review: () => get<AfterAction>("/api/after-action"),
  verify: () => post<AuditVerifyResult>("/api/audit/verify"),
  tamperDemo: () => post<TamperDemo>("/api/audit/tamper-demo", {}),
};

/** True when the server answered "not here": the route is not built on this stack yet. */
export const isMissingRoute = (err: unknown): boolean =>
  err instanceof ApiError && (err.status === 404 || err.status === 501);
