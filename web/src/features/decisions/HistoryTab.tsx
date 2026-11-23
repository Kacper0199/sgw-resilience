import { History } from "lucide-react";
import { EmptyState } from "@/components/sgw";
import { Skeleton } from "@/components/ui/skeleton";
import type { AuditEvent, ProposalCard } from "@/lib/api";
import { formatRecorded } from "@/lib/time";
import { PaneSection } from "./PaneSection";
import { useAudit } from "./queries";
import { personName } from "./ui";

interface Entry {
  at: string;
  text: string;
  who: string;
  detail?: string;
  order: number;
}

const KIND_TEXT: Record<string, string> = {
  approval_recorded: "Signature recorded",
  execution_token_issued: "Go-ahead issued",
  execution_token_burned: "Go-ahead used",
  proposal_created: "Decision proposed",
  proposal_updated: "Decision updated",
  break_glass_used: "Emergency approval used",
  break_glass_cosigned: "Emergency approval co-signed",
  proposal_withdrawn: "Decision withdrawn",
  approval_withdrawn: "Signature withdrawn",
};

const AFTER_SAME_MINUTE: Record<string, number> = { execution_token_issued: 1 };

const textOf = (e: AuditEvent): string => {
  if (e.kind === "approval_recorded" && e.decision === "reject") return "Sent back";
  return KIND_TEXT[e.kind] ?? sentence(e.kind);
};

const PERSON_REASON = new Set(["approval_recorded", "approval_withdrawn", "proposal_withdrawn"]);

const sentence = (kind: string) => {
  const text = kind.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};

const SYSTEM_ACTOR: Record<string, string> = {
  "clock-replanner": "System: Deadline planner",
  approval: "SGW, after the approvals",
  breakglass: "SGW, emergency approval check",
};

const spoken = (id: string) => id.replace(/[_-]+/g, " ").replace(/\bps17\b/gi, "PS-17");

/** A system actor in plain words: "system:clock-replanner" is the Deadline planner, "rule:ps17_pressure_floor" an SGW rule. */
export function systemActorName(actorId: string): string {
  const id = actorId.replace(/^system:/, "");
  if (SYSTEM_ACTOR[id]) return SYSTEM_ACTOR[id];
  if (id.startsWith("rule:")) return "SGW rules (automatic)";
  if (id.startsWith("agent:")) return `${personName(id.slice("agent:".length))} (AI draft)`;
  const text = spoken(id);
  return `System: ${text.charAt(0).toUpperCase()}${text.slice(1)}`;
}

const actorName = (e: AuditEvent) =>
  e.actor_type === "user" ? personName(e.actor_id) : systemActorName(e.actor_id);

const voidedText = (reason: string | null, byStop: boolean) =>
  byStop
    ? "Signature voided — the stop level was raised"
    : reason && /^advisory\b/i.test(reason)
      ? "Signature voided — a new advisory moved the deadline"
      : "Signature voided — the decision changed";

/** Each person's earliest signatures, as many as the card lists voided for them, are the voided ones. */
function voidedSignatures(card: ProposalCard, events: AuditEvent[]): Map<AuditEvent, string> {
  const left = new Map<string, { reason: string | null; byStop: boolean }[]>();
  for (const v of [...(card.voided_approvals ?? [])].sort(
    (a, b) => a.proposal_version - b.proposal_version,
  )) {
    left.set(v.approver_id, [
      ...(left.get(v.approver_id) ?? []),
      { reason: v.reason, byStop: v.voided_by_version === null },
    ]);
  }
  const out = new Map<AuditEvent, string>();
  const signed = events
    .filter((e) => e.kind === "approval_recorded" && e.actor_type === "user")
    .sort((a, b) => Date.parse(a.occurred_at) - Date.parse(b.occurred_at));
  for (const e of signed) {
    const voided = left.get(e.actor_id)?.shift();
    if (voided !== undefined) out.set(e, voidedText(voided.reason, voided.byStop));
  }
  return out;
}

export function entriesFrom(card: ProposalCard, events: AuditEvent[]): Entry[] {
  const voided = voidedSignatures(card, events);
  const out: Entry[] = events.map((e) => ({
    at: e.occurred_at,
    text: voided.get(e) ?? textOf(e),
    who: actorName(e),
    detail: PERSON_REASON.has(e.kind) && e.reason ? e.reason : undefined,
    order: e.seq + (AFTER_SAME_MINUTE[e.kind] ?? 0) * 1e12,
  }));
  const bg = card.break_glass;
  if (bg && !events.some((e) => e.kind === "break_glass_used")) {
    out.push({
      at: bg.used_at_utc,
      text: `Emergency approval: ${bg.reason}`,
      who: personName(bg.ic_id),
      order: 0,
    });
  }
  return out.sort((a, b) => Date.parse(b.at) - Date.parse(a.at) || b.order - a.order);
}

/** The ledger timeline of one decision, newest first. */
export function HistoryTab({ card }: { card: ProposalCard }) {
  const { data, isPending, error } = useAudit(card.proposal_id);
  if (isPending) return <Skeleton className="h-24" />;
  const entries = entriesFrom(card, data ?? []);
  return (
    <PaneSection title="History" info="ledger">
      <div data-testid="history">
        {error && entries.length === 0 ? (
          <EmptyState role="alert" icon={History} title="Your role can't view this history." />
        ) : entries.length === 0 ? (
          <p className="m-0 text-[13px] text-muted">No history yet.</p>
        ) : (
          <ol className="m-0 list-none p-0 pb-1" data-testid="timeline">
            {entries.map((e) => (
              <li
                key={`${e.at}-${e.text}-${e.who}`}
                className="relative border-l border-hair-strong pb-3 pl-4 last:pb-0"
              >
                <span aria-hidden className="absolute top-1.5 -left-[3.5px] size-1.5 rounded-full bg-ink" />
                <p className="m-0 text-[13px] font-medium">{e.text}</p>
                {e.detail && <p className="m-0 text-[13px] text-ink-2">{e.detail}</p>}
                <p className="m-0 text-label text-muted tnum">
                  {e.who}, {formatRecorded(e.at)}
                </p>
              </li>
            ))}
          </ol>
        )}
      </div>
    </PaneSection>
  );
}
