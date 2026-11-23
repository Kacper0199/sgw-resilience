import type { GlossaryEntry } from "./glossary";

export const ETR_GLOSSARY = {
  etr: {
    term: "Global ETR",
    text: "When 90% of the peak customers out have power again. Publishing needs Command and Operations to sign.",
  },
  etr_area: {
    term: "ETR by area",
    text: "The estimate per crew yard's area. Still out: share of the area's peak. The bar is the 80% range; the line, the middle.",
  },
  review_draft: {
    term: "Review draft",
    text: "AI drafts the after-action review from the audit log. Every number has a source. Nothing is filed.",
  },
} as const satisfies Record<string, GlossaryEntry>;
