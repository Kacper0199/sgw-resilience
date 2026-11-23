import { useSyncExternalStore } from "react";
import type { ProposalCard } from "@/lib/api";
import { onSessionReset } from "@/lib/sessionReset";
import type { QueueItem } from "./useQueue";

export interface VoidedApproval {
  approver_id: string;
  function: ProposalCard["approvals"][number]["function"];
  at: string;
  /** The version the signature was given on. */
  version: number;
  /** The version that replaced it. */
  voidedBy: number;
}

const STORAGE = "sgw.voidedApprovals";
type Listener = () => void;

function load(): Record<string, VoidedApproval[]> {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE) ?? "{}") as Record<string, VoidedApproval[]>;
  } catch {
    return {};
  }
}

let voided: Record<string, VoidedApproval[]> = load();
const lastSeen = new Map<string, { version: number; approvals: ProposalCard["approvals"] }>();
const listeners = new Set<Listener>();

/**
 * The card lists only the signatures valid for its version. When a new version arrives and a signature given on the
 * previous one is gone, it was voided; the Approval tab keeps it struck through so the history stays readable.
 */
export function observeVersions(items: QueueItem[]): void {
  let changed = false;
  for (const { card } of items) {
    if (!card) continue;
    const prev = lastSeen.get(card.proposal_id);
    lastSeen.set(card.proposal_id, { version: card.proposal_version, approvals: card.approvals });
    if (!prev || card.proposal_version <= prev.version) continue;
    const gone = prev.approvals.filter(
      (a) =>
        a.decision !== "reject" &&
        !card.approvals.some((b) => b.approver_id === a.approver_id && b.at === a.at),
    );
    if (gone.length === 0) continue;
    const known = voided[card.proposal_id] ?? [];
    voided = {
      ...voided,
      [card.proposal_id]: [
        ...known,
        ...gone.map((a) => ({
          approver_id: a.approver_id,
          function: a.function,
          at: a.at,
          version: prev.version,
          voidedBy: card.proposal_version,
        })),
      ],
    };
    changed = true;
  }
  if (changed) {
    try {
      sessionStorage.setItem(STORAGE, JSON.stringify(voided));
    } catch {
      // storage unavailable: voided rows last for this page view only
    }
    for (const l of listeners) l();
  }
}

export function resetVoided(): void {
  voided = {};
  lastSeen.clear();
  try {
    sessionStorage.removeItem(STORAGE);
  } catch {
    // nothing stored
  }
  for (const l of listeners) l();
}

const subscribe = (l: Listener) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

const EMPTY: VoidedApproval[] = [];

onSessionReset(resetVoided);

/** Only signatures replaced by a version the card has actually reached count as voided. */
export function voidedUpTo(list: VoidedApproval[], currentVersion: number): VoidedApproval[] {
  const kept = list.filter((v) => v.voidedBy <= currentVersion);
  return kept.length === list.length ? list : kept;
}

const useObserved = (proposalId: string): VoidedApproval[] =>
  useSyncExternalStore(subscribe, () => voided[proposalId] ?? EMPTY);

/** The signatures the server keeps as voided, so every browser sees them; ones this browser watched go are added. */
export function voidedOf(card: ProposalCard, observed: VoidedApproval[]): VoidedApproval[] {
  const server: VoidedApproval[] = (card.voided_approvals ?? [])
    .filter((v) => v.decision !== "reject")
    .map((v) => ({
      approver_id: v.approver_id,
      function: v.function,
      at: v.at,
      version: v.proposal_version,
      voidedBy: v.voided_by_version ?? card.proposal_version,
    }));
  const seen = (o: VoidedApproval) =>
    server.some((v) => v.approver_id === o.approver_id && v.version === o.version);
  return voidedUpTo([...server, ...observed.filter((o) => !seen(o))], card.proposal_version);
}

export const useVoidedApprovals = (card: ProposalCard): VoidedApproval[] =>
  voidedOf(card, useObserved(card.proposal_id));
