import { PERSONAS } from "@/auth/personas";
import type { ApprovalFunction } from "@/contracts/vocab.gen";
import type { ProposalCard } from "@/lib/api";

export interface Signature {
  function: ApprovalFunction;
  approver_id: string;
  at: string;
}

type Signable = Pick<ProposalCard, "approvals" | "functions_required"> & {
  break_glass?: ProposalCard["break_glass"];
};

/** Who signed, per team: the recorded signatures, plus an emergency approval (Command alone) and its co-sign,
 * which live on the break-glass record instead of as signatures. */
export function signaturesOf(card: Signable): Signature[] {
  const out: Signature[] = card.approvals
    .filter((a) => a.decision !== "reject")
    .map((a) => ({ function: a.function, approver_id: a.approver_id, at: a.at }));
  const bg = card.break_glass;
  if (!bg) return out;
  const has = (f: ApprovalFunction) => out.some((s) => s.function === f);
  if (card.functions_required.includes("command") && !has("command")) {
    out.push({ function: "command", approver_id: bg.ic_id, at: bg.used_at_utc });
  }
  if (bg.cosigned_by) {
    const own = PERSONAS.find((p) => p.user_id === bg.cosigned_by)?.function;
    const fn =
      own && card.functions_required.includes(own) ? own : card.functions_required.find((f) => !has(f));
    if (fn && !has(fn)) {
      out.push({ function: fn, approver_id: bg.cosigned_by, at: bg.cosigned_at_utc ?? bg.used_at_utc });
    }
  }
  return out;
}
