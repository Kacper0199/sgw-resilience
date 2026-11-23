import { RefreshCw } from "lucide-react";
import { FUNCTION_LABEL } from "@/auth/personas";
import { InfoTip } from "@/components/sgw";
import type { ProposalCard } from "@/lib/api";
import { formatRecorded } from "@/lib/time";
import { humanizeKey } from "./Envelope";
import { useVoidedApprovals } from "./voidedApprovals";

/** Shown once a newer version replaced signed ones: what changed, who has to sign again. */
export function VersionVoidBanner({ card }: { card: ProposalCard }) {
  const voided = useVoidedApprovals(card);
  const changes = card.changes_since_version ?? [];
  if (card.proposal_version <= 1 || (voided.length === 0 && changes.length === 0)) return null;
  const changed = changes.map(humanizeKey);
  return (
    <div
      role="status"
      data-testid="void-banner"
      className="flex items-start gap-2 border-l-[3px] border-blue bg-selected px-3 py-2 text-[13px]"
    >
      <RefreshCw className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0">
        <p className="m-0 font-medium">
          Version {card.proposal_version} replaced an earlier version
          <InfoTip term="version_void" />
        </p>
        {voided.length > 0 ? (
          <p className="m-0 text-muted">
            {voided
              .map((v) => `${FUNCTION_LABEL[v.function]} signed v${v.version} on ${formatRecorded(v.at)}`)
              .join("; ")}
            . That signature no longer counts. Sign this version again.
          </p>
        ) : (
          <p className="m-0 text-muted">Earlier signatures no longer count. Sign this version again.</p>
        )}
        {changed.length > 0 && <p className="m-0 text-muted">What changed: {changed.join(", ")}.</p>}
      </div>
    </div>
  );
}
