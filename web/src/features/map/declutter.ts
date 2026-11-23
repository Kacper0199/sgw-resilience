export interface ScreenPoint {
  id: string;
  x: number;
  y: number;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Markers closer than `size` px form a cluster; a cluster of two or more is fanned out around its centre so every
 * marker stays whole and easy to hit. Alone, a marker keeps its position. Order follows `points`.
 */
export function spreadMarkers(points: ScreenPoint[], size: number): Map<string, { x: number; y: number }> {
  const group = points.map((_, i) => i);
  const find = (i: number): number => {
    let r = i;
    while (group[r] !== r) r = group[r] as number;
    return r;
  };
  for (let i = 0; i < points.length; i++) {
    for (let j = i + 1; j < points.length; j++) {
      const a = points[i] as ScreenPoint;
      const b = points[j] as ScreenPoint;
      if (Math.hypot(a.x - b.x, a.y - b.y) < size) group[find(j)] = find(i);
    }
  }
  const clusters = new Map<number, ScreenPoint[]>();
  points.forEach((p, i) => {
    const key = find(i);
    clusters.set(key, [...(clusters.get(key) ?? []), p]);
  });
  const placed = new Map<string, { x: number; y: number }>();
  for (const members of clusters.values()) {
    const n = members.length;
    if (n === 1) {
      const only = members[0] as ScreenPoint;
      placed.set(only.id, { x: only.x, y: only.y });
      continue;
    }
    const cx = members.reduce((s, p) => s + p.x, 0) / n;
    const cy = members.reduce((s, p) => s + p.y, 0) / n;
    const radius = Math.max(size * 0.8, (size * 0.62) / Math.sin(Math.PI / n));
    members.forEach((p, k) => {
      const angle = -Math.PI / 2 + (2 * Math.PI * k) / n;
      placed.set(p.id, { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) });
    });
  }
  return placed;
}

export interface LabelCandidate extends ScreenPoint {
  w: number;
  h: number;
  /** Higher wins a contested spot. */
  weight: number;
}

const overlaps = (a: Rect, b: Rect, gap: number) =>
  a.x < b.x + b.w + gap && b.x < a.x + a.w + gap && a.y < b.y + b.h + gap && b.y < a.y + a.h + gap;

/** Greedy, collision-free label placement: heaviest first; a label that touches a placed one or an obstacle is dropped.
 * Without a `view` nothing is dropped for lying outside it, so the choice does not change while the map pans. */
export function placeLabels(
  candidates: LabelCandidate[],
  view: { w: number; h: number } | null,
  obstacles: Rect[] = [],
  gap = 3,
): LabelCandidate[] {
  const taken: Rect[] = [...obstacles];
  const kept: LabelCandidate[] = [];
  for (const c of [...candidates].sort((a, b) => b.weight - a.weight)) {
    const box = { x: c.x - c.w / 2, y: c.y - c.h / 2, w: c.w, h: c.h };
    const inside = !view || (box.x >= 0 && box.y >= 0 && box.x + box.w <= view.w && box.y + box.h <= view.h);
    if (!inside || taken.some((t) => overlaps(box, t, gap))) continue;
    taken.push(box);
    kept.push(c);
  }
  return kept;
}

interface Point {
  x: number;
  y: number;
}

const STEP = 10;
const REACH = 200;
const ANGLES = 24;

/**
 * Keeps `anchored` markers where they are and moves the others the shortest way to a spot that touches no other
 * marker and lies at least `clear` px from every `keepClear` point, so pulse rings stay free of badges. Markers
 * are placed in input order, each on the nearest free spot of a widening spiral around its own position.
 */
export function relaxMarkers(
  placed: Map<string, Point>,
  anchored: ReadonlySet<string>,
  keepClear: Point[],
  size: number,
  clear: number,
): Map<string, Point> {
  const out = new Map<string, Point>();
  for (const [id, p] of placed) if (anchored.has(id)) out.set(id, { ...p });
  const free = (c: Point) =>
    keepClear.every((k) => Math.hypot(c.x - k.x, c.y - k.y) >= clear) &&
    [...out.values()].every((o) => Math.hypot(c.x - o.x, c.y - o.y) >= size + 2);
  const nearestFree = (p: Point): Point => {
    if (free(p)) return { ...p };
    for (let r = STEP; r <= REACH; r += STEP) {
      for (let k = 0; k < ANGLES; k++) {
        const a = (2 * Math.PI * k) / ANGLES;
        const c = { x: p.x + r * Math.cos(a), y: p.y + r * Math.sin(a) };
        if (free(c)) return c;
      }
    }
    return { ...p };
  };
  for (const [id, p] of placed) if (!anchored.has(id)) out.set(id, nearestFree(p));
  return new Map([...placed.keys()].map((id) => [id, out.get(id) as Point]));
}
