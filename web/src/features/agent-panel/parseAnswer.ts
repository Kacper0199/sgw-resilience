import type { AnswerPath, ParsedAnswer, PlatformRow, SourceCite } from "./types";

export const NOT_IN_DOCS = "This is not in the documents.";
export const READ_ONLY_PREFIX = "This is not in the documents or platform data";
const M2_PREFIX = "Evidence gathered for this question";
/** The lead of the plain fallback answer: "Answer from platform data. <why the AI did not write it>". */
export const M2_LEAD = "Answer from platform data.";
const UNVERIFIED = "[field record, unverified]";
const CITE_LINE = /^\[(\d+)\] (?:(\[field record, unverified\]) )?(.+?), (.+), ([^,]+): "(.*)"$/s;
const PLATFORM_LINE = /^\[([A-Za-z][^\]]*)\] (.+)$/;

/** The path the server names; older messages carry only text, so the path is read from the fixed wording. */
export function inferPath(text: string): AnswerPath {
  const flat = text.trim();
  if (flat === NOT_IN_DOCS || flat.startsWith(READ_ONLY_PREFIX)) return "not_in_documents";
  if (flat.startsWith(M2_PREFIX) || flat.startsWith(M2_LEAD)) return "m2";
  return "llm";
}

function parseCite(line: string): SourceCite | null {
  const m = CITE_LINE.exec(line.trim());
  if (!m) return null;
  return {
    n: Number(m[1]),
    unverified: m[2] === UNVERIFIED,
    citationId: m[3],
    section: m[4],
    pages: m[5],
    quote: m[6],
  };
}

/** Splits the rendered reply the server sends into its sentences, its numbered sources and its platform rows. */
export function parseAnswer(text: string, path?: AnswerPath | null): ParsedAnswer {
  const kind = path ?? inferPath(text);
  if (kind === "not_in_documents" || kind === "guide")
    return { kind, body: text.trim(), lead: null, citations: [], platform: [] };

  if (kind === "m2") {
    const [lead = "", ...lines] = text.split("\n");
    const citations: SourceCite[] = [];
    const platform: PlatformRow[] = [];
    for (const line of lines) {
      const cite = parseCite(line);
      if (cite) {
        citations.push(cite);
        continue;
      }
      const row = PLATFORM_LINE.exec(line.trim());
      if (row) platform.push({ id: row[1], text: row[2] });
    }
    return { kind, body: "", lead: lead.trim(), citations, platform };
  }

  const marker = text.indexOf("\n\nSources:\n");
  if (marker === -1) return { kind, body: text.trim(), lead: null, citations: [], platform: [] };
  const citations = text
    .slice(marker + "\n\nSources:\n".length)
    .split("\n")
    .map(parseCite)
    .filter((c): c is SourceCite => c !== null);
  return { kind, body: text.slice(0, marker).trim(), lead: null, citations, platform: [] };
}

export type Segment = { kind: "text"; text: string; at: number } | { kind: "source"; n: number; at: number };

/** Turns "[1]" marks in a body into source segments; a mark with no matching source stays plain text. */
export function splitMarkers(body: string, known: ReadonlySet<number>): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of body.matchAll(/\[(\d+)\]/g)) {
    const n = Number(m[1]);
    if (!known.has(n)) continue;
    const at = m.index ?? 0;
    if (at > last) out.push({ kind: "text", text: body.slice(last, at), at: last });
    out.push({ kind: "source", n, at });
    last = at + m[0].length;
  }
  if (last < body.length) out.push({ kind: "text", text: body.slice(last), at: last });
  return out;
}
