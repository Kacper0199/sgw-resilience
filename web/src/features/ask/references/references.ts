import { decisionHref } from "@/lib/links";
import type { Reference, ReferenceKind } from "../../agent-panel/types";
import { decisionTitle } from "../../decisions/actionTypes";

export const REFERENCE_KINDS: readonly ReferenceKind[] = [
  "decision",
  "asset",
  "county",
  "zone",
  "advisory",
  "crew",
  "yard",
  "readiness",
  "clause",
  "photo",
  "surge",
  "gauge",
  "check",
];

const q = encodeURIComponent;

/**
 * Where a reference opens. A decision opens through its proposal (`proposalOf` maps the decision case id the
 * answer names to the proposal the queue lists); without one there is no page to open, so it gets no href
 * and reads as plain text. A clause has no page either: it opens the Sources panel.
 */
export function referenceHref(ref: Reference, proposalOf: (caseId: string) => string | null): string | null {
  switch (ref.kind) {
    case "decision": {
      const proposal = proposalOf(ref.id);
      return proposal ? decisionHref(proposal) : null;
    }
    case "asset":
      return `/map?asset=${q(ref.id)}`;
    case "county":
      return `/map?county=${q(ref.id)}`;
    case "zone":
      return `/water?zone=${q(ref.id)}`;
    case "advisory":
      return "/forecast?tab=changes";
    case "crew":
      return `/crews?crew=${q(ref.id)}`;
    case "yard":
      return `/crews?yard=${q(ref.id)}`;
    case "readiness":
    case "check":
      return `/readiness?check=${q(ref.id)}`;
    case "photo":
      return `/crews?photo=${q(ref.id)}`;
    case "surge":
      return surgeHref(ref.id);
    case "gauge":
      return `/map?gauge=${q(ref.id)}`;
    case "clause":
      return null;
  }
}

/** A surge reference is `<county id>@<ISO time>`: the map opens that county at that time. */
export function surgeHref(id: string): string {
  const [county, at] = id.split("@");
  return `/map?county=${q(county ?? id)}${at ? `&at=${q(at)}` : ""}`;
}

/** The words the answer uses for a reference: the id itself, the county's name, or "latest advisory". */
export function referencePattern(ref: Reference): RegExp {
  const literal = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  if (ref.kind === "advisory") return /\blatest advisory\b/gi;
  if (ref.kind === "surge") return new RegExp(literal(ref.label), "g");
  if (ref.kind === "county") return new RegExp(`\\b${literal(ref.label.replace(/ County$/, ""))}\\b`, "g");
  return new RegExp(`(?<![\\w-])${literal(ref.id)}(?:['’]s)?(?![\\w-])`, "g");
}

const SPELLED_OUT: readonly ReferenceKind[] = ["advisory", "county", "surge", "clause"];

const PUMP_STATION = /^PS-\d+$/;

const keepsText = (ref: Reference): boolean =>
  SPELLED_OUT.includes(ref.kind) || ref.label === ref.id || PUMP_STATION.test(ref.id);

/**
 * What a chip reads: the plain name of the thing ("Pre-position crews at Sandhill and Millpond yards"), never its id,
 * also inside a decision title ("Restore FDR-CLB-0817 …" reads "Restore feeder 0817 …", as the Decisions page shows it).
 * In brackets right after the place its label names ("PS-38 (GEN-PS38-…)"), the place is not repeated: "onsite generator".
 */
export function chipText(ref: Reference, text: string, before = ""): string {
  if (keepsText(ref)) return text;
  const place = / at (\S+)$/.exec(ref.label)?.[1];
  if (place && before.trimEnd().endsWith(`${place} (`)) {
    const thing = ref.label.slice(0, -` at ${place}`.length);
    return thing.charAt(0).toLowerCase() + thing.slice(1);
  }
  const label = ref.kind === "decision" ? decisionTitle(ref.label) : ref.label;
  return label + (/['’]s$/.exec(text)?.[0] ?? "");
}

const stem = (word: string): string => word.toLowerCase().slice(0, 4);

const contentWords = (text: string): string[] => text.match(/[A-Za-z]{4,}/g) ?? [];

/** ", hooking up the portable generator," after a decision whose label is "Hook up the portable generator at PS-17". */
function appositiveLength(after: string, ref: Reference): number {
  if (ref.kind !== "decision") return 0;
  const m = /^,\s*([^,.;:()]{3,60}),/.exec(after);
  const words = contentWords(m?.[1] ?? "");
  if (!m || words.length === 0) return 0;
  const label = new Set(contentWords(ref.label).map(stem));
  return words.every((w) => label.has(stem(w))) ? m[0].length : 0;
}

/** An id the answer follows with the same words as its label ("DC-… Secure water supply: …") is one mention, not two. */
function restatedLength(after: string, ref: Reference): number {
  if (keepsText(ref)) return 0;
  const gap = /^[\s:\u2013-]*/.exec(after)?.[0].length ?? 0;
  const next = after.slice(gap, gap + ref.label.length);
  if (next.toLowerCase() === ref.label.toLowerCase()) return gap + ref.label.length;
  return appositiveLength(after, ref);
}

/**
 * "Hook up the portable generator at PS-17 (DC-D3-PS17-POWER)": the title and its id in brackets are one mention. When
 * the brackets go on ("… (DC-D3-PS17-FUEL, Sep 26, 21:59 ET)"), the id is dropped and the brackets reopen after the chip.
 */
function titledLength(
  before: string,
  after: string,
  ref: Reference,
): { before: number; after: number; reopen: boolean } {
  const none = { before: 0, after: 0, reopen: false };
  const goesOn = /^[,;]\s*/.exec(after);
  if (ref.kind !== "decision" || !(after.startsWith(")") || goesOn)) return none;
  const open = /\s*\($/.exec(before);
  if (!open) return none;
  const head = before.slice(0, open.index);
  if (!head.toLowerCase().endsWith(ref.label.toLowerCase())) return none;
  const lead = before.length - open.index + ref.label.length;
  return goesOn
    ? { before: lead, after: goesOn[0].length, reopen: true }
    : { before: lead, after: 1, reopen: false };
}

export type RefSegment =
  | { kind: "text"; text: string; at: number }
  | { kind: "ref"; text: string; ref: Reference; at: number };

const refKey = (ref: Reference): string => `${ref.kind}:${ref.id}`;

/**
 * Splits text into plain runs and chips: the first free mention of each reference becomes its chip. `used` holds the
 * references already shown as a chip elsewhere in the same answer; they stay plain text here and are added once shown.
 */
export function splitReferences(
  text: string,
  refs: readonly Reference[],
  used: Set<string> = new Set(),
): RefSegment[] {
  const spans: { start: number; end: number; ref: Reference; reopen: boolean }[] = [];
  const titledFirst = [
    ...refs.filter((r) => r.kind === "decision"),
    ...refs.filter((r) => r.kind !== "decision"),
  ];
  for (const ref of titledFirst) {
    if (used.has(refKey(ref))) continue;
    for (const m of text.matchAll(referencePattern(ref))) {
      const at = m.index ?? 0;
      const titled = titledLength(text.slice(0, at), text.slice(at + m[0].length), ref);
      const start = at - titled.before;
      const end = titled.after
        ? at + m[0].length + titled.after
        : at + m[0].length + restatedLength(text.slice(at + m[0].length), ref);
      if (!spans.some((s) => start < s.end && end > s.start)) {
        spans.push({ start, end, ref, reopen: titled.reopen });
        break;
      }
    }
  }
  spans.sort((a, b) => a.start - b.start);
  for (const s of spans) used.add(refKey(s.ref));
  const out: RefSegment[] = [];
  let last = 0;
  for (const s of spans) {
    if (s.start > last) out.push({ kind: "text", text: text.slice(last, s.start), at: last });
    const reopened = s.reopen ? text.slice(s.start, s.end).replace(/\s*\([^(]*$/, "") : "";
    out.push({
      kind: "ref",
      text: s.reopen ? reopened : text.slice(s.start, s.end),
      ref: s.ref,
      at: s.start,
    });
    if (s.reopen) out.push({ kind: "text", text: " (", at: s.start + 0.5 });
    last = s.end;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last), at: last });
  return out;
}

/**
 * One chip per reference per answer: each text of the answer split in order, a reference chipped only at its first
 * mention. `plain` lists references that never become chips here (a clause whose source badge the answer shows).
 */
export function splitAnswer(
  texts: readonly string[],
  refs: readonly Reference[],
  plain: readonly Reference[] = [],
): RefSegment[][] {
  const used = new Set(plain.map(refKey));
  return texts.map((text) => splitReferences(text, refs, used));
}
