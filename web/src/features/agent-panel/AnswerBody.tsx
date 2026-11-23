import { Database, SearchX, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { InfoTip } from "@/components/sgw";
import { RefSegments, splitAnswer } from "../ask/references";
import { M2_LEAD, NOT_IN_DOCS, READ_ONLY_PREFIX, type Segment, splitMarkers } from "./parseAnswer";
import { SourceBadge } from "./SourceBadge";
import type { AnswerReason, ParsedAnswer, Reference, SourceCite } from "./types";

interface Props {
  parsed: ParsedAnswer;
  reason?: AnswerReason | null;
  tainted: boolean;
  activeN: number | null;
  onSelect: (n: number) => void;
  references?: readonly Reference[];
  question?: string;
}

const POLISH =
  /[ąćęłńśźż]|\b(?:co|gdzie|jak|jest|czy|ile|ilu|jakie|które|ktore|teraz|sytuacja|klientów|prądu)\b/i;
const M2_LEAD_PL = "Odpowiedź z danych platformy.";

/** The fixed lines of an answer in the question's language: Polish for a Polish question, English otherwise. */
const COPY = {
  en: {
    unavailable: "The assistant is not available",
    retry: "Try again in a moment.",
    notFound: "I couldn't find this",
    notFoundBody:
      "Nothing in SGW documents or platform data answers it. Try asking it another way, or start from one of these.",
    unverified: "Uses an unverified field report. Treat it as unconfirmed, not as procedure.",
  },
  pl: {
    unavailable: "Asystent jest niedostępny",
    retry: "Spróbuj ponownie za chwilę.",
    notFound: "Nie znalazłem tego",
    notFoundBody:
      "Dokumenty i dane platformy SGW nie odpowiadają na to. Zadaj pytanie inaczej albo zacznij od jednego z tych.",
    unverified:
      "Korzysta z niepotwierdzonego raportu z terenu. Traktuj go jako niepotwierdzony, nie jako procedurę.",
  },
};
type Lang = keyof typeof COPY;
export const languageOf = (question: string | undefined): Lang =>
  question && POLISH.test(question) ? "pl" : "en";

/** The first source of a document a clause chip names (its citation id starts with the document id). */
const sourceOf = (parsed: ParsedAnswer, docId: string): number | null =>
  parsed.citations.find((c) => c.citationId.startsWith(docId))?.n ?? null;

/** Clauses the answer cites with a source badge: the badge is their one chip, so their mentions stay plain text. */
const badgedClauses = (parsed: ParsedAnswer, references: readonly Reference[]): Reference[] =>
  references.filter((r) => r.kind === "clause" && sourceOf(parsed, r.id) !== null);

/** Only the first badge of each document is shown; later marks of the same document would repeat it. */
function firstBadges(lines: readonly Segment[][], byN: Map<number, SourceCite>): Set<string> {
  const docs = new Set<string>();
  const shown = new Set<string>();
  lines.forEach((segs, line) => {
    for (const s of segs) {
      if (s.kind !== "source") continue;
      const doc = byN.get(s.n)?.citationId ?? String(s.n);
      if (docs.has(doc)) continue;
      docs.add(doc);
      shown.add(`${line}:${s.at}`);
    }
  });
  return shown;
}

interface CitedProps {
  lines: readonly string[];
  parsed: ParsedAnswer;
  references: readonly Reference[];
  activeN: number | null;
  onSelect: (n: number) => void;
  wrap: (children: ReactNode, line: number) => ReactNode;
}

/** Lines of an answer with their chips and source badges: one chip per reference and one badge per document. */
function CitedLines({ lines, parsed, references, activeN, onSelect, wrap }: CitedProps) {
  const known = new Set(parsed.citations.map((c) => c.n));
  const byN = new Map(parsed.citations.map((c) => [c.n, c]));
  const marked = lines.map((line) => splitMarkers(line, known));
  const texts = marked.flatMap((segs) => segs.flatMap((s) => (s.kind === "text" ? [s.text] : [])));
  const chips = splitAnswer(texts, references, badgedClauses(parsed, references));
  const shown = firstBadges(marked, byN);
  const onClause = (docId: string) => {
    const n = sourceOf(parsed, docId);
    if (n !== null) onSelect(n);
  };
  let k = 0;
  return (
    <>
      {marked.map((segs, line) =>
        wrap(
          segs.map((s) => {
            if (s.kind === "text") {
              return <RefSegments key={s.at} segments={chips[k++] ?? []} onClause={onClause} />;
            }
            if (!shown.has(`${line}:${s.at}`)) return null;
            return (
              <SourceBadge
                key={s.at}
                n={s.n}
                citationId={byN.get(s.n)?.citationId ?? ""}
                unverified={byN.get(s.n)?.unverified ?? false}
                active={activeN === s.n}
                onSelect={onSelect}
              />
            );
          }),
          line,
        ),
      )}
    </>
  );
}

function Notice({ tainted, lang }: { tainted: boolean; lang: Lang }) {
  if (!tainted) return null;
  return (
    <p className="m-0 mt-2 flex items-center gap-1.5 text-[13px] text-warn">
      <TriangleAlert aria-hidden className="size-3.5 shrink-0" />
      {COPY[lang].unverified}
      <InfoTip term="unverified_record" />
    </p>
  );
}

function Plain({
  testId,
  icon: Icon,
  title,
  info,
  children,
}: {
  testId: string;
  icon: typeof SearchX;
  title: string;
  info?: "not_in_documents" | "findings_only";
  children: ReactNode;
}) {
  return (
    <div data-testid={testId} className="flex gap-3 border-l-2 border-hair-strong py-0.5 pl-4">
      <Icon aria-hidden className="mt-0.5 size-5 shrink-0 text-muted" strokeWidth={1.5} />
      <div className="min-w-0">
        <p className="m-0 flex items-center gap-1 text-[15px] font-semibold">
          {title}
          {info && <InfoTip term={info} />}
        </p>
        {children}
      </div>
    </div>
  );
}

function Unavailable({ lang }: { lang: Lang }) {
  return (
    <Plain testId="unavailable" icon={TriangleAlert} title={COPY[lang].unavailable}>
      <p className="m-0 mt-1 text-[14px] text-muted">{COPY[lang].retry}</p>
    </Plain>
  );
}

function Abstain({ body, lang }: { body: string; lang: Lang }) {
  const legacy = body === NOT_IN_DOCS || body.startsWith(READ_ONLY_PREFIX);
  if (!legacy)
    return (
      <p className="m-0 text-reading whitespace-pre-line" data-testid="answer-text">
        {body}
      </p>
    );
  return (
    <Plain testId="abstain" icon={SearchX} title={COPY[lang].notFound} info="not_in_documents">
      <p className="m-0 mt-1 text-[14px] text-muted">{COPY[lang].notFoundBody}</p>
    </Plain>
  );
}

/** The code-written answer: its lead says why the AI did not write it; rows carry their chips and source badges. */
function FindingsOnly({
  parsed,
  reason,
  activeN,
  onSelect,
  references = [],
}: Omit<Props, "tainted" | "question">) {
  const leadText = [M2_LEAD, M2_LEAD_PL].find((l) => parsed.lead?.startsWith(l));
  const plain = leadText !== undefined;
  const fromData = plain || reason !== "checks_failed";
  const why = plain ? (parsed.lead ?? "").slice(leadText.length).trim() : "";
  const rows = parsed.platform.map((r) => r.text);
  const cited = new Set(rows.flatMap((t) => [...t.matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1]))));
  const listed = parsed.citations.filter((c) => !cited.has(c.n));
  return (
    <Plain
      testId="findings-only"
      icon={fromData ? Database : SearchX}
      title={plain ? leadText.slice(0, -1) : fromData ? "From platform data" : "Sources only"}
      info={fromData ? undefined : "findings_only"}
    >
      {why && (
        <p className="m-0 mt-0.5 text-[13px] text-muted" data-testid="fallback-why">
          {why}
        </p>
      )}
      {!fromData && (
        <p className="m-0 mt-1 text-[14px] text-muted">
          The written answer failed its source check, so only the sources are shown.
        </p>
      )}
      {rows.length > 0 && (
        <ul className="m-0 mt-2 flex list-none flex-col gap-1.5 p-0 text-[14px] leading-6">
          <CitedLines
            lines={rows}
            parsed={parsed}
            references={references}
            activeN={activeN}
            onSelect={onSelect}
            wrap={(children, line) => (
              <li key={line} className="min-w-0 break-words">
                {children}
              </li>
            )}
          />
        </ul>
      )}
      {listed.length > 0 && (
        <ul className="m-0 mt-2.5 flex list-none flex-col gap-1.5 p-0 text-[14px]">
          {listed.map((c) => (
            <li key={c.n} className="flex items-center gap-2">
              <SourceBadge
                n={c.n}
                citationId={c.citationId}
                unverified={c.unverified}
                active={activeN === c.n}
                onSelect={onSelect}
              />
              <span className="min-w-0 break-words text-muted">{c.section}</span>
            </li>
          ))}
        </ul>
      )}
    </Plain>
  );
}

export function AnswerBody({ parsed, reason, tainted, activeN, onSelect, references = [], question }: Props) {
  const lang = languageOf(question);
  if (parsed.kind === "not_in_documents")
    return reason === "llm_unavailable" ? (
      <Unavailable lang={lang} />
    ) : (
      <Abstain body={parsed.body} lang={lang} />
    );
  if (parsed.kind === "m2") {
    return (
      <>
        <FindingsOnly
          parsed={parsed}
          reason={reason}
          activeN={activeN}
          onSelect={onSelect}
          references={references}
        />
        <Notice tainted={tainted} lang={lang} />
      </>
    );
  }
  return (
    <>
      <p className="m-0 text-reading whitespace-pre-line" data-testid="answer-text">
        <CitedLines
          lines={[parsed.body]}
          parsed={parsed}
          references={references}
          activeN={activeN}
          onSelect={onSelect}
          wrap={(children, line) => <span key={line}>{children}</span>}
        />
      </p>
      <Notice tainted={tainted} lang={lang} />
    </>
  );
}
