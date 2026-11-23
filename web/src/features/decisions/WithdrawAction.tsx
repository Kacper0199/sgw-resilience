import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { useMe } from "@/auth/useSession";
import { ReasonDialog } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { ApiError, type ProposalCard, post } from "@/lib/api";

const WITHDRAWABLE = new Set(["draft", "proposed", "in_review", "escalated"]);

export type WithdrawKind = "proposal" | "signature" | null;

/** The proposer may withdraw an open decision; a signer may take back their own signature while others still sign. */
export function withdrawKind(card: ProposalCard, userId: string | undefined): WithdrawKind {
  if (!userId) return null;
  const approvedNonT3 = card.state === "approved" && card.tier !== "T3";
  if (card.proposed_by.user_id === userId && (WITHDRAWABLE.has(card.state) || approvedNonT3))
    return "proposal";
  const signed = card.approvals.some((a) => a.approver_id === userId && a.decision === "approve");
  return card.state === "in_review" && signed ? "signature" : null;
}

const TEXT = {
  proposal: {
    button: "Withdraw…",
    title: "Withdraw this decision",
    description: "It leaves the queue for everyone. Signatures already given no longer count.",
    confirm: "Withdraw",
    done: "Decision withdrawn.",
  },
  signature: {
    button: "Withdraw my signature…",
    title: "Withdraw your signature",
    description: "The decision goes back to waiting for your team.",
    confirm: "Withdraw signature",
    done: "Your signature was withdrawn.",
  },
} as const;

export function WithdrawAction({ card }: { card: ProposalCard }) {
  const me = useMe().data;
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const kind = withdrawKind(card, me?.user_id);
  const withdraw = useMutation({
    mutationFn: (reason: string) =>
      post(`/api/proposals/${encodeURIComponent(card.proposal_id)}/withdraw`, { reason }),
    onSuccess: () => {
      setOpen(false);
      if (kind) toast.success(TEXT[kind].done);
      return Promise.all([
        qc.invalidateQueries({ queryKey: ["proposals"] }),
        qc.invalidateQueries({ queryKey: ["notifications"] }),
      ]);
    },
  });
  if (!kind) return null;
  const text = TEXT[kind];
  const error = withdraw.error
    ? withdraw.error instanceof ApiError && withdraw.error.status === 409
      ? "The decision changed meanwhile. Close and look again."
      : "Couldn't withdraw. Try again."
    : null;
  return (
    <>
      <Button
        variant="ghost"
        className="self-start text-crit hover:bg-crit-soft"
        onClick={() => setOpen(true)}
      >
        {text.button}
      </Button>
      <ReasonDialog
        open={open}
        title={text.title}
        description={text.description}
        confirm={text.confirm}
        pending={withdraw.isPending}
        error={error}
        onConfirm={(reason) => withdraw.mutate(reason)}
        onClose={() => {
          setOpen(false);
          withdraw.reset();
        }}
      />
    </>
  );
}
