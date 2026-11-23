import { useQuery } from "@tanstack/react-query";
import { etrApi } from "./api";
import type { AfterActionDraft, EtrView } from "./types";

export const ETR_KEY = ["etr"] as const;
export const REVIEW_DRAFTS_KEY = ["after-action", "drafts"] as const;

const FAST_MS = 1500;
const SLOW_MS = 5000;

/** Polls fast while a draft or a publication is in flight, slowly while signatures are open. */
export function etrRefetch(view: EtrView | undefined, publishing: boolean): number | false {
  if (!view) return false;
  const state = view.publication?.state;
  const stopped = view.publication?.run_status === "error" || view.publication?.run_status === "cancelled";
  if (stopped && state !== "executed") return false;
  if (view.drafting || (publishing && state !== "executed")) return FAST_MS;
  if (state === "proposed" || state === "in_review" || state === "escalated" || state === "approved")
    return SLOW_MS;
  return false;
}

export const useEtr = (publishing = false) =>
  useQuery({
    queryKey: ETR_KEY,
    queryFn: etrApi.view,
    retry: false,
    refetchInterval: (q) => etrRefetch(q.state.data, publishing),
  });

export const reviewRunning = (drafts: AfterActionDraft[] | undefined): boolean =>
  Boolean(drafts?.some((d) => d.status === "running"));

export const useReviewDrafts = () =>
  useQuery({
    queryKey: REVIEW_DRAFTS_KEY,
    queryFn: etrApi.reviewDrafts,
    retry: false,
    refetchInterval: (q) => (reviewRunning(q.state.data) ? FAST_MS : false),
  });
