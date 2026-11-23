import type { AnswerExtras, AnswerLink, AnswerPhoto, RefusalKind } from "./types";
import { NO_EXTRAS } from "./types";

const REFUSALS: readonly RefusalKind[] = ["unrelated", "write_action", "injection"];

const text = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);

const records = (v: unknown): Record<string, unknown>[] =>
  Array.isArray(v) ? v.filter((x): x is Record<string, unknown> => typeof x === "object" && x !== null) : [];

function toLink(r: Record<string, unknown>): AnswerLink | null {
  const label = text(r.label);
  const href = text(r.href);
  return label && href ? { label, href, kind: text(r.kind) ?? undefined } : null;
}

function toPhoto(r: Record<string, unknown>): AnswerPhoto | null {
  const id = text(r.photo_id);
  const thumbUrl = text(r.thumb_url);
  if (!id || !thumbUrl) return null;
  return {
    id,
    thumbUrl,
    href: text(r.href) ?? `/crews?photo=${encodeURIComponent(id)}`,
    caption: text(r.caption) ?? "Damage photo",
    provenance: text(r.provenance),
  };
}

const questions = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((s): s is string => typeof s === "string" && s.trim().length > 0) : [];

const present = <T>(x: T | null): x is T => x !== null;

/** What an assistant message or answer artifact adds to its text, read defensively: older messages carry none of it. */
export function wireExtras(m: Record<string, unknown> | null | undefined): AnswerExtras {
  if (!m) return NO_EXTRAS;
  const links = records(m.links).map(toLink).filter(present);
  const photos = records(m.photos).map(toPhoto).filter(present);
  const suggestions = questions(m.suggestions);
  const didYouMean = questions(m.did_you_mean);
  const refusal = REFUSALS.find((k) => k === m.refusal) ?? null;
  if (links.length + photos.length + suggestions.length + didYouMean.length === 0 && !refusal)
    return NO_EXTRAS;
  return { links, photos, suggestions, didYouMean, refusal };
}
