import type { components } from "@/contracts/api.gen";
import type { SourceCite } from "./types";

export type WireCitation = Pick<
  components["schemas"]["MessageCitation"],
  "n" | "citation_id" | "section" | "pages" | "cited_text" | "unverified"
>;

export const toSourceCite = (c: WireCitation): SourceCite => ({
  n: c.n,
  citationId: c.citation_id,
  section: c.section,
  pages: c.pages,
  quote: c.cited_text,
  unverified: c.unverified,
});
