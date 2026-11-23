import type { Domain, NoRegretVerdict, UiSeverity } from "@/contracts/vocab.gen";
import type { Asset, Me, MissedDecisionCase } from "@/lib/api";
import { type Bucket, bucketOf, isPending } from "./severity";
import { type Owner, ownerOf, severityOf, timingOf } from "./ui";
import { type QueueItem, signBlock } from "./useQueue";

export type QueueFilter = "waiting" | "all" | "decided";
export type TimingFilter = "all" | NoRegretVerdict;
export type DomainFilter = "all" | Domain;
export type OwnerFilter = "all" | string;

export interface QueueRow {
  id: string;
  caseId: string;
  title: string;
  item: QueueItem;
  domain: Domain | undefined;
  owner: Owner;
  decideByMs: number;
  severity: UiSeverity;
  verdict: NoRegretVerdict;
  impact: number;
  pinned: boolean;
  open: boolean;
  bucket: Bucket;
}

/** A Closed row for a decision whose deadline passed with no proposal: missed, nothing to open. */
export interface MissedRow {
  kind: "missed";
  id: string;
  caseId: string;
  title: string;
  domain: Domain;
  decideBy: string;
  decideByMs: number;
}

export type ListRow = QueueRow | MissedRow;

export const isMissed = (r: ListRow): r is MissedRow => "kind" in r && r.kind === "missed";

export function toMissedRows(
  cases: readonly MissedDecisionCase[],
  domain: DomainFilter,
  owner: OwnerFilter,
  find: string,
): MissedRow[] {
  if (owner !== "all") return [];
  const words = find.trim().toLowerCase();
  return cases
    .filter((c) => domain === "all" || c.domain === domain)
    .filter((c) => !words || `${c.title} ${c.decision_case_id}`.toLowerCase().includes(words))
    .map((c) => ({
      kind: "missed",
      id: `missed:${c.decision_case_id}`,
      caseId: c.decision_case_id,
      title: c.title,
      domain: c.domain,
      decideBy: c.effective_decide_by_utc,
      decideByMs: Date.parse(c.effective_decide_by_utc),
    }));
}

/** The Closed page with the missed rows in deadline order (or after the rest when sorted otherwise). */
export function withMissed(
  rows: QueueRow[],
  missed: MissedRow[],
  byDeadline: boolean,
  desc: boolean,
): ListRow[] {
  if (!byDeadline) return [...rows, ...missed];
  const before = (m: MissedRow, r: QueueRow) =>
    desc ? m.decideByMs > r.decideByMs : m.decideByMs < r.decideByMs;
  const queue = [...missed].sort((a, b) =>
    desc ? b.decideByMs - a.decideByMs : a.decideByMs - b.decideByMs,
  );
  const out: ListRow[] = [];
  for (const r of rows) {
    while (queue[0] && before(queue[0], r)) out.push(queue.shift() as MissedRow);
    out.push(r);
  }
  return [...out, ...queue];
}

export const SEVERITY_RANK: Record<UiSeverity, number> = {
  critical: 0,
  severe: 1,
  elevated: 2,
  advisory: 3,
  normal: 4,
  unknown_stale: 5,
};

/** Impact: the most critical asset the decision touches, then the people it serves, then the critical path. */
export function impactOf(item: QueueItem, assets: ReadonlyMap<string, Asset>): number {
  const targets = (item.card?.target_ids ?? []).map((id) => assets.get(id)).filter((a): a is Asset => !!a);
  const criticality = Math.max(0, ...targets.map((a) => a.criticality ?? 0));
  const served = Math.max(0, ...targets.map((a) => a.customers_served ?? 0));
  return (item.summary.on_critical_path ? 1e10 : 0) + criticality * 1e7 + Math.min(served, 9_999_999);
}

export function toRows(
  items: QueueItem[],
  me: Me | null | undefined,
  now: string,
  assets: ReadonlyMap<string, Asset>,
): QueueRow[] {
  return items.map((item) => {
    const s = item.summary;
    const open = isPending(s.state);
    return {
      id: s.proposal_id,
      caseId: s.decision_case_id,
      title: s.title,
      item,
      domain: item.card?.case.domain,
      owner: ownerOf(s),
      decideByMs: Date.parse(s.effective_decide_by_utc),
      severity: severityOf(s),
      verdict: item.card ? timingOf(item.card) : "n/a",
      impact: impactOf(item, assets),
      pinned: open && Boolean(me && signBlock(me, s) === null),
      open,
      bucket: bucketOf(s, now),
    };
  });
}

/** Closed last, the signer's own work first, then decide-by, then impact (higher first), then id for a stable order. */
export function compareDecideBy(a: QueueRow, b: QueueRow): number {
  if (a.open !== b.open) return a.open ? -1 : 1;
  if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
  return a.decideByMs - b.decideByMs || b.impact - a.impact || a.id.localeCompare(b.id);
}

export const compareSeverity = (a: QueueRow, b: QueueRow) =>
  SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || compareDecideBy(a, b);

export type SortKey = "decide" | "severity" | "title" | "owner";

export function groupOf(row: QueueRow): "mine" | Bucket {
  return row.pinned ? "mine" : row.bucket;
}

/** The legacy shape the hotkeys and tests use: pool, pinned and the keyboard order for a filter. */
export function buildQueue(
  items: QueueItem[],
  me: Me | null | undefined,
  filter: QueueFilter,
  domain: DomainFilter,
  owner: OwnerFilter = "all",
  now = "1970-01-01T00:00:00Z",
) {
  const rows = toRows(items, me, now, new Map());
  const open = rows.filter((r) => r.open);
  const mine = rows.filter((r) => r.pinned);
  const pool = (filter === "waiting" ? mine : rows)
    .filter((r) => domain === "all" || r.domain === domain)
    .filter((r) => owner === "all" || r.owner.fn === owner)
    .sort(compareDecideBy);
  return { open, mine, pool, order: pool.map((r) => r.id) };
}
