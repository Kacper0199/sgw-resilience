import { ApiError } from "./api";

export type LoadFailure = "no_access" | "failed";

/** A failed read is never an empty list: 401/403 is "no access", everything else "couldn't load". */
export const loadFailure = (error: unknown): LoadFailure =>
  error instanceof ApiError && (error.status === 401 || error.status === 403) ? "no_access" : "failed";

/** The sentence a list shows instead of its empty state, for example "You don't have access to boil-water notices." */
export const loadFailureTitle = (error: unknown, thing: string): string =>
  loadFailure(error) === "no_access" ? `You don't have access to ${thing}.` : `Couldn't load ${thing}.`;

/** The short line a key number shows instead of a value it could not read. */
export const loadFailureLine = (error: unknown): string =>
  loadFailure(error) === "no_access" ? "You don't have access" : "Couldn't load";

/** A 404 means "not there yet", which a page may word as its own empty state; any other error may not. */
export const isMissing = (error: unknown): boolean => error instanceof ApiError && error.status === 404;
