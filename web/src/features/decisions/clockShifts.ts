import { useEffect, useSyncExternalStore } from "react";
import type { ProposalSummary } from "@/lib/api";
import { onSessionReset, resetSession } from "@/lib/sessionReset";
import { formatDuration, formatEtZ } from "@/lib/time";
import type { QueueItem } from "./useQueue";

type ServerClockShift = NonNullable<ProposalSummary["clock_shift"]>;

export interface ClockShift {
  caseId: string;
  from: string;
  to: string;
  atMs: number;
}

const STORAGE = "sgw.clockShifts";
const FLASH_MS = 6000;

type Listener = () => void;

function load(): Record<string, ClockShift> {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE) ?? "{}") as Record<string, ClockShift>;
  } catch {
    return {};
  }
}

let shifts: Record<string, ClockShift> = load();
let flashing: ReadonlySet<string> = new Set();
const lastSeen = new Map<string, string>();
const listeners = new Set<Listener>();
const timers = new Map<string, ReturnType<typeof setTimeout>>();

const emit = () => {
  for (const l of listeners) l();
};

function record(caseId: string, from: string, to: string) {
  shifts = { ...shifts, [caseId]: { caseId, from, to, atMs: Date.now() } };
  try {
    sessionStorage.setItem(STORAGE, JSON.stringify(shifts));
  } catch {
    // storage unavailable: the chip lasts for this page view only
  }
  flashing = new Set([...flashing, caseId]);
  clearTimeout(timers.get(caseId));
  timers.set(
    caseId,
    setTimeout(() => {
      flashing = new Set([...flashing].filter((c) => c !== caseId));
      emit();
    }, FLASH_MS),
  );
}

/** Feed the latest queue; a changed effective decide-by becomes a shift the chip and the outline read. */
export function observeClocks(items: QueueItem[]): void {
  let changed = false;
  for (const { summary: s } of items) {
    const prev = lastSeen.get(s.decision_case_id);
    lastSeen.set(s.decision_case_id, s.effective_decide_by_utc);
    if (prev && prev !== s.effective_decide_by_utc) {
      record(s.decision_case_id, prev, s.effective_decide_by_utc);
      changed = true;
    }
  }
  if (changed) emit();
}

export function resetClockShifts(): void {
  shifts = {};
  flashing = new Set();
  lastSeen.clear();
  for (const t of timers.values()) clearTimeout(t);
  timers.clear();
  try {
    sessionStorage.removeItem(STORAGE);
  } catch {
    // nothing stored
  }
  emit();
}

const subscribe = (l: Listener) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

export function useClockShifts(items?: QueueItem[]) {
  useEffect(() => {
    if (items) observeClocks(items);
  }, [items]);
  const all = useSyncExternalStore(subscribe, () => shifts);
  const flash = useSyncExternalStore(subscribe, () => flashing);
  return { shifts: all, flashing: flash };
}

export function describeShift(s: ClockShift): { text: string; earlier: boolean } {
  const delta = Math.round((Date.parse(s.to) - Date.parse(s.from)) / 60_000);
  const earlier = delta < 0;
  return {
    earlier,
    text: `${earlier ? "Earlier" : "Later"} by ${formatDuration(delta)}, was ${formatEtZ(s.from)}`,
  };
}

const howMoved = (s: ClockShift): string => describeShift(s).text.split(", was ")[0]?.toLowerCase() ?? "";

/** The note above the list for the decisions in view whose deadline moved: the one by name, or how many ("3 deadlines moved earlier by 1 h 16 m"). */
export function movedNote(moved: readonly { title: string; shift: ClockShift }[]): string | null {
  const first = moved[0];
  if (!first) return null;
  if (moved.length === 1) return `${first.title}: deadline moved ${howMoved(first.shift)}`;
  const amounts = new Set(moved.map((m) => howMoved(m.shift)));
  const ways = new Set(moved.map((m) => describeShift(m.shift).earlier));
  const way = describeShift(first.shift).earlier ? " earlier" : " later";
  const tail = amounts.size === 1 ? ` ${howMoved(first.shift)}` : ways.size === 1 ? way : "";
  return `${moved.length} deadlines moved${tail}`;
}

onSessionReset(resetClockShifts);

/**
 * The server's move against the previous advisory first, so every browser that opens the moment sees it; a move
 * this browser watched happen is the fallback. Either one holds only while the decide-by is the one it moved to.
 */
export function currentShift(
  shifts: Record<string, ClockShift>,
  caseId: string,
  effectiveDecideBy: string,
  server?: ServerClockShift | null,
): ClockShift | undefined {
  if (server && server.shift_min !== 0)
    return { caseId, from: server.previous_effective_decide_by_utc, to: effectiveDecideBy, atMs: 0 };
  const shift = shifts[caseId];
  return shift && shift.to === effectiveDecideBy ? shift : undefined;
}

let lastScenarioMs: number | null = null;

/** A scenario clock that moves backwards (reset or rewind) makes everything learned from the old run stale. */
export function observeScenarioTime(iso: string | undefined): void {
  if (!iso) return;
  const ms = Date.parse(iso);
  if (lastScenarioMs !== null && ms < lastScenarioMs) resetSession();
  lastScenarioMs = ms;
}
