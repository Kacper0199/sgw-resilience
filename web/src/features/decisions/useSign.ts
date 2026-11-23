import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, type ProposalCard } from "@/lib/api";

export type SignDecision = "approve" | "reject" | "break_glass" | "cosign";

export interface SignInput {
  decision: SignDecision;
  note?: string;
  password?: string;
}

export type SignProblem =
  | { kind: "step_up"; wrongPassword: boolean }
  | { kind: "stale"; version: number }
  | { kind: "error"; message: string };

/**
 * The T3 two-function flow. The signature binds to the version and action hash the person was looking at when
 * the dialog opened; if the live card moves on (stream update or a 412), signing is blocked until they review it.
 */
export function useSign(card: ProposalCard) {
  const qc = useQueryClient();
  const [problem, setProblem] = useState<SignProblem | null>(null);
  const [bound, setBound] = useState({
    id: card.proposal_id,
    version: card.proposal_version,
    hash: card.action_hash,
  });
  const otherDecision = card.proposal_id !== bound.id;
  const stale = otherDecision || card.proposal_version !== bound.version || card.action_hash !== bound.hash;

  const mutation = useMutation({
    mutationFn: async (input: SignInput) => {
      if (input.password) await api.stepUp(input.password);
      if (input.decision === "cosign") {
        await api.cosign(bound.id);
        return { remaining: [] as string[] };
      }
      if (input.decision === "break_glass") {
        await api.breakGlass(bound.id, {
          proposal_version: bound.version,
          action_hash: bound.hash,
          reason: input.note?.trim() ?? "",
        });
        return { remaining: [] as string[] };
      }
      const res = await api.approve(bound.id, {
        decision: input.decision,
        proposal_version: bound.version,
        action_hash: bound.hash,
        reason_code: input.decision === "reject" ? "needs_info" : null,
        note: input.note?.trim() || null,
      });
      return { remaining: res.remaining_functions as string[] };
    },
    onMutate: () => setProblem(null),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: ["proposals"], exact: true }),
        qc.invalidateQueries({ queryKey: ["proposals", bound.id] }),
      ]),
    onError: (err) => {
      if (!(err instanceof ApiError))
        return setProblem({ kind: "error", message: "Can't reach SGW. Check your connection." });
      if (err.code === "STEP_UP_REQUIRED") return setProblem({ kind: "step_up", wrongPassword: false });
      if (err.code === "STEP_UP_FAILED") return setProblem({ kind: "step_up", wrongPassword: true });
      if (err.status === 412) {
        const version =
          (err.body as { current_version?: number } | undefined)?.current_version ?? card.proposal_version;
        void qc.invalidateQueries({ queryKey: ["proposals"], exact: true });
        void qc.invalidateQueries({ queryKey: ["proposals", card.proposal_id] });
        return setProblem({ kind: "stale", version });
      }
      setProblem({ kind: "error", message: err.message });
    },
  });

  return {
    ...mutation,
    problem,
    stale,
    otherDecision,
    liveVersion: card.proposal_version,
    boundVersion: bound.version,
    sign: (input: SignInput, options?: Parameters<typeof mutation.mutate>[1]) => {
      if (!stale) mutation.mutate(input, options);
    },
    review: () => {
      setBound({ id: card.proposal_id, version: card.proposal_version, hash: card.action_hash });
      setProblem(null);
    },
  };
}
