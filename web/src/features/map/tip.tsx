import { createContext, useContext, useLayoutEffect, useMemo, useRef, useSyncExternalStore } from "react";
import { cn } from "@/lib/cn";

export interface TipState {
  text: string;
  /** Optional muted lines below, separated by newlines. */
  detail?: string;
  x: number;
  y: number;
  /** Width of the map container, so the tip flips to the left of the cursor near the right edge. */
  width: number;
  /** Set for a tip that belongs to a marker: it sits on that side of the marker (x, y is its centre). */
  side?: TipSide;
  /** Extra distance from the marker in px, when the tip had to move out of a crowd. */
  away?: number;
}

export type TipSide = "above" | "below" | "right" | "left";

export const TIP_HEIGHT = 26;
const TIP_GAP = 6;
const TIP_CHAR = 6.6;
const TIP_PAD = 22;

export const tipWidth = (text: string): number => Math.min(280, Math.ceil(text.length * TIP_CHAR + TIP_PAD));

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

const covered = (b: Box, others: Box[]): number =>
  others.reduce((sum, o) => {
    const w = Math.min(b.x + b.w, o.x + o.w) - Math.max(b.x, o.x);
    const h = Math.min(b.y + b.h, o.y + o.h) - Math.max(b.y, o.y);
    return w > 0 && h > 0 ? sum + w * h : sum;
  }, 0);

const AWAY_STEPS = [0, 10, 20, 30];
const SIDES: TipSide[] = ["above", "below", "right", "left"];

function tipBox(side: TipSide, marker: Box, tip: { w: number; h: number }, away: number): Box {
  const cx = marker.x + marker.w / 2;
  const cy = marker.y + marker.h / 2;
  const reach = marker.w / 2 + TIP_GAP + away;
  switch (side) {
    case "above":
      return { x: cx - tip.w / 2, y: cy - reach - tip.h, w: tip.w, h: tip.h };
    case "below":
      return { x: cx - tip.w / 2, y: cy + reach, w: tip.w, h: tip.h };
    case "right":
      return { x: cx + reach, y: cy - tip.h / 2, w: tip.w, h: tip.h };
    default:
      return { x: cx - reach - tip.w, y: cy - tip.h / 2, w: tip.w, h: tip.h };
  }
}

/**
 * Where a marker's tip covers no other marker and stays inside the map: nearest first, above, below, right, then
 * left, then a little further out. In a crowd with no clear spot it takes the side that covers the least.
 */
export function chooseTipSide(
  marker: Box,
  others: Box[],
  tip: { w: number; h: number },
  view: { w: number; h: number },
): { side: TipSide; away: number } {
  const inside = (b: Box) => b.x >= 0 && b.x + b.w <= view.w && b.y >= 0 && b.y + b.h <= view.h;
  for (const away of AWAY_STEPS) {
    for (const side of SIDES) {
      const box = tipBox(side, marker, tip, away);
      if (inside(box) && covered(box, others) === 0) return { side, away };
    }
  }
  const fitting = SIDES.filter((side) => inside(tipBox(side, marker, tip, 0)));
  const pool = fitting.length > 0 ? fitting : SIDES;
  const side = pool.reduce((best, s) =>
    covered(tipBox(s, marker, tip, 0), others) < covered(tipBox(best, marker, tip, 0), others) ? s : best,
  );
  return { side, away: 0 };
}

const sideTransform = (tip: TipState, markerReach: number): string => {
  const g = markerReach + TIP_GAP + (tip.away ?? 0);
  switch (tip.side) {
    case "above":
      return `translate(calc(${tip.x}px - 50%), calc(${tip.y - g}px - 100%))`;
    case "below":
      return `translate(calc(${tip.x}px - 50%), ${tip.y + g}px)`;
    case "right":
      return `translate(${tip.x + g}px, calc(${tip.y}px - 50%))`;
    case "left":
      return `translate(calc(${tip.x - g}px - 100%), calc(${tip.y}px - 50%))`;
    default:
      return "";
  }
};

export interface TipStore {
  get: () => TipState | null;
  set: (next: TipState | null) => void;
  subscribe: (cb: () => void) => () => void;
}

export function createTipStore(): TipStore {
  let state: TipState | null = null;
  const subscribers = new Set<() => void>();
  return {
    get: () => state,
    set: (next) => {
      state = next;
      for (const cb of subscribers) cb();
    },
    subscribe: (cb) => {
      subscribers.add(cb);
      return () => subscribers.delete(cb);
    },
  };
}

export const TipContext = createContext<TipStore | null>(null);

export const useTipStore = () => useMemo(createTipStore, []);
export const useTip = () => useContext(TipContext);

export const TIP_EDGE = 8;

/** The horizontal shift that keeps a tip of `left`..`right` (px inside the map) at least `TIP_EDGE` from both edges. */
export function edgeShift(left: number, right: number, width: number): number {
  if (left < TIP_EDGE) return TIP_EDGE - left;
  if (right > width - TIP_EDGE) return Math.min(0, width - TIP_EDGE - right);
  return 0;
}

/** A tooltip at the cursor over the map: one line (and optional muted detail lines), truncated, never
 * intercepts the pointer, and kept inside the map on both sides. */
export function MapTip({ store }: { store: TipStore }) {
  const tip = useSyncExternalStore(store.subscribe, store.get);
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    const map = el?.offsetParent;
    if (!tip || !el || !map) return;
    el.style.translate = "";
    const box = el.getBoundingClientRect();
    const frame = map.getBoundingClientRect();
    el.style.translate = `${edgeShift(box.left - frame.left, box.right - frame.left, frame.width)}px 0`;
  });
  if (!tip) return null;
  const flip = tip.x > tip.width * 0.6 || tip.x + (tip.detail ? 400 : 300) > tip.width;
  const transform = tip.side
    ? sideTransform(tip, 13)
    : `translate(${flip ? `calc(${tip.x - 12}px - 100%)` : `${tip.x + 14}px`}, ${tip.y + 16}px)`;
  return (
    <div
      ref={ref}
      role="tooltip"
      data-testid="map-tip"
      style={{ transform }}
      className={cn(
        "pointer-events-none absolute top-0 left-0 z-30 truncate rounded-md bg-surface px-2.5 py-1 text-[12px] font-medium whitespace-nowrap text-ink shadow-float tnum",
        tip.detail ? "max-w-[380px]" : "max-w-[280px]",
      )}
    >
      {tip.text}
      {tip.detail?.split("\n").map((line) => (
        <span key={line} className="block truncate text-[11.5px] font-normal text-ink-2">
          {line}
        </span>
      ))}
    </div>
  );
}
