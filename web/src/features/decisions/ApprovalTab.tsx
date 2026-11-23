import { Check, Circle } from "lucide-react";
import { FUNCTION_LABEL } from "@/auth/personas";
import { useMe } from "@/auth/useSession";
import { SourceLine } from "@/components/sgw";
import type { ApprovalFunction } from "@/contracts/vocab.gen";
import type { ProposalCard } from "@/lib/api";
import { formatRecorded } from "@/lib/time";
import { BreakGlassCard } from "./BreakGlassCard";
import { EnvelopeCard } from "./Envelope";
import { PaneSection } from "./PaneSection";
import { signaturesOf } from "./signatures";
import { personName, proposerLine } from "./ui";
import { useVoidedApprovals } from "./voidedApprovals";

const STATE_LINE: Record<string, string> = {
  approved: "Approved",
  rejected: "Sent back",
  withdrawn: "Withdrawn",
  expired: "Expired",
  executed: "Carried out",
};

/** Signing is parallel: your own function leads when it is missing, then every other function that still has to sign. */
export function waitingLine(missing: ApprovalFunction[], mine: ApprovalFunction | undefined): string {
  if (missing.length === 0) return "Ready";
  const ordered = [...missing].sort((a, b) => Number(b === mine) - Number(a === mine));
  return `Waiting for ${ordered.map((f) => `${FUNCTION_LABEL[f]}${f === mine ? " (you)" : ""}`).join(", ")}`;
}

/** Whose turn it is first, then who signed (function, person, time, version), then what is missing. */
export function ApprovalTab({ card }: { card: ProposalCard }) {
  const me = useMe().data;
  const voided = useVoidedApprovals(card);
  const proposer = proposerLine(card);
  const signatures = signaturesOf(card);
  const signedBy = (fn: string) => signatures.find((a) => a.function === fn);
  const missing = card.functions_required.filter((f) => !signedBy(f));
  const head = STATE_LINE[card.state] ?? waitingLine(missing, me?.function);
  return (
    <div className="flex flex-col gap-3" data-testid="approval-card">
      <PaneSection title={<span data-testid="approval-head">{head}</span>} info="approval">
        <ul className="m-0 list-none divide-y divide-hair p-0" aria-label="Signatures">
          {card.functions_required.map((fn) => {
            const signed = signedBy(fn);
            return (
              <li key={fn} className="flex items-baseline gap-3 py-2 text-[13px]" data-testid="signature-row">
                {signed ? (
                  <Check className="size-4 shrink-0 translate-y-0.5 text-ok" aria-hidden />
                ) : (
                  <Circle className="size-4 shrink-0 translate-y-0.5 text-muted" aria-hidden />
                )}
                <span className="w-32 shrink-0 font-medium">{FUNCTION_LABEL[fn]}</span>
                {signed ? (
                  <span className="min-w-0 text-muted tnum">
                    {personName(signed.approver_id)}, {formatRecorded(signed.at)}, v{card.proposal_version}
                  </span>
                ) : (
                  <span className="text-muted">Not signed yet</span>
                )}
              </li>
            );
          })}
          {voided.map((v) => (
            <li
              key={`${v.approver_id}-${v.at}`}
              data-testid="voided-row"
              className="flex items-baseline gap-3 py-2 text-[13px] text-muted"
            >
              <Circle className="size-4 shrink-0 translate-y-0.5" aria-hidden />
              <span className="w-32 shrink-0 line-through">{FUNCTION_LABEL[v.function]}</span>
              <span className="min-w-0 tnum">
                <span className="line-through">
                  {personName(v.approver_id)}, {formatRecorded(v.at)}, v{v.version}
                </span>{" "}
                <span className="text-ink">No longer valid as of v{v.voidedBy}</span>
              </span>
            </li>
          ))}
        </ul>
        {proposer && <SourceLine className="mt-2">{`Proposed by ${proposer}`}</SourceLine>}
      </PaneSection>
      {card.envelope && <EnvelopeCard envelope={card.envelope} />}
      {card.break_glass && <BreakGlassCard card={card} />}
    </div>
  );
}
