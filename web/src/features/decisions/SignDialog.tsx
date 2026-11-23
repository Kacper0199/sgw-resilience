import { useEffect, useState } from "react";
import { toast } from "sonner";
import { FUNCTION_LABEL } from "@/auth/personas";
import { useMe } from "@/auth/useSession";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { POLICIES } from "@/contracts/policies.gen";
import type { ProposalCard } from "@/lib/api";
import { usePhase } from "@/lib/PhaseProvider";
import { formatEtZ, formatRelative } from "@/lib/time";
import { decisionTitle } from "./actionTypes";
import { signaturesOf } from "./signatures";
import { timingOf, timingText } from "./ui";
import { type SignDecision, useSign } from "./useSign";
import { VerdictText } from "./VerdictText";

interface Props {
  card: ProposalCard;
  decision: SignDecision;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Opens the emergency approval dialog; offered in the footer of the sign dialog only. */
  onApproveAlone?: () => void;
  /** The scenario clock, for "in 12 h 4 m" beside the deadline. */
  now?: string;
}

export function SignDialog({ card, decision, open, onOpenChange, onApproveAlone, now }: Props) {
  const me = useMe().data;
  const phase = usePhase();
  const sign = useSign(card);
  const closeDialog = sign.otherDecision;
  useEffect(() => {
    if (closeDialog) onOpenChange(false);
  }, [closeDialog, onOpenChange]);
  const [note, setNote] = useState("");
  const [password, setPassword] = useState("");
  const needsPassword = sign.problem?.kind === "step_up";
  const outdated = sign.stale || sign.problem?.kind === "stale";
  const sendBack = decision === "reject";
  const breakGlass = decision === "break_glass";
  const coSign = decision === "cosign";
  const needsReason = sendBack || breakGlass;
  const pending = sign.isPending;

  const submit = () =>
    sign.sign(
      { decision, note, password: needsPassword ? password : undefined },
      {
        onSuccess: (res) => {
          toast.success(
            coSign
              ? "Co-signed. The emergency approval is now complete."
              : breakGlass
                ? "Approved alone in an emergency. A second team must co-sign."
                : sendBack
                  ? "Sent back for more information."
                  : res.remaining.length
                    ? "Signed. Waiting for the other team."
                    : "Signed. The decision is approved.",
          );
          setNote("");
          setPassword("");
          onOpenChange(false);
        },
      },
    );

  const fn = me ? FUNCTION_LABEL[me.function] : "";
  const signedCount = signaturesOf(card).length;
  const required = card.functions_required.map((f) => FUNCTION_LABEL[f]);
  const title = coSign
    ? "Co-sign emergency approval"
    : breakGlass
      ? "Emergency approval"
      : sendBack
        ? "Send back"
        : "Sign decision";
  const label = pending
    ? "Signing…"
    : needsPassword
      ? "Sign"
      : coSign
        ? "Co-sign"
        : breakGlass
          ? "Approve alone"
          : sendBack
            ? "Send back"
            : "Sign";
  return (
    <Dialog open={open} onOpenChange={(o) => !sign.isPending && onOpenChange(o)}>
      <DialogContent>
        <div>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className="mt-1">
            {decisionTitle(card.title)}
            {me && !sendBack && `. Signing as ${fn}, version ${sign.boundVersion}`}
          </DialogDescription>
        </div>
        <dl className="m-0 grid grid-cols-[96px_1fr] gap-x-4 gap-y-2 border-y border-hair py-3 text-[13px]">
          <dt className="font-semibold text-muted">Decide by</dt>
          <dd className="m-0 tnum">
            <span className="font-semibold">{formatEtZ(card.effective_decide_by_utc)}</span>
            {now && <span className="text-muted">, {formatRelative(card.effective_decide_by_utc, now)}</span>}
          </dd>
          {timingText(timingOf(card), phase) && (
            <>
              <dt className="font-semibold text-muted">Timing</dt>
              <dd className="m-0">
                <VerdictText verdict={timingOf(card)} />
              </dd>
            </>
          )}
          <dt className="font-semibold text-muted">Signatures</dt>
          <dd className="m-0 tnum">
            {signedCount} of {required.length}. {required.join(" and ")}.
          </dd>
        </dl>
        {breakGlass && (
          <p className="m-0 text-[13px] text-ink-2">
            You approve alone. A second team must co-sign within{" "}
            {POLICIES.policy_break_glass_cosign_hours.value} hours. Every emergency approval is reviewed
            later.
          </p>
        )}
        {(needsReason || needsPassword) && (
          <div className="flex flex-col gap-3">
            {needsReason && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="note">{breakGlass ? "Why is this an emergency?" : "What is missing?"}</Label>
                <Textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} />
              </div>
            )}
            {needsPassword && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="stepup">Enter your password to sign</Label>
                <Input
                  id="stepup"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="border-2 border-blue"
                />
              </div>
            )}
          </div>
        )}
        {sign.problem?.kind === "step_up" && sign.problem.wrongPassword && (
          <p role="alert" className="m-0 text-[13px] text-error">
            Wrong password.
          </p>
        )}
        {outdated && (
          <p role="alert" className="m-0 text-[13px] text-error">
            This decision changed to version{" "}
            {sign.stale
              ? sign.liveVersion
              : sign.problem?.kind === "stale"
                ? sign.problem.version
                : sign.liveVersion}
            . Review the update, then sign again.
          </p>
        )}
        {sign.problem?.kind === "error" && (
          <p role="alert" className="m-0 text-[13px] text-error">
            {sign.problem.message}
          </p>
        )}
        <DialogFooter className="justify-between">
          <span>
            {onApproveAlone && decision === "approve" && !sign.stale && (
              <Button
                variant="ghost"
                className="text-crit hover:bg-crit-soft"
                disabled={sign.isPending}
                onClick={onApproveAlone}
              >
                Approve alone…
              </Button>
            )}
          </span>
          <span className="flex items-center gap-2">
            <Button disabled={sign.isPending} onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            {sign.stale ? (
              <Button variant="primary" data-autofocus onClick={sign.review}>
                Review v{sign.liveVersion}
              </Button>
            ) : (
              <Button
                variant={breakGlass ? "destructive-solid" : "primary"}
                data-autofocus={decision === "approve" || coSign ? "" : undefined}
                onClick={submit}
                disabled={sign.isPending || (needsReason && !note.trim()) || (needsPassword && !password)}
              >
                {label}
              </Button>
            )}
          </span>
        </DialogFooter>
        <p className="m-0 text-[12px] text-muted">
          {sendBack
            ? "Your reason is recorded in the audit log."
            : "Your signature is recorded in the audit log."}
        </p>
      </DialogContent>
    </Dialog>
  );
}
