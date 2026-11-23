import { FileText, X } from "lucide-react";
import { useEffect, useRef } from "react";
import { CountBadge, DomainMark, InfoTip } from "@/components/sgw";
import { IconButton } from "@/components/ui/icon-button";
import { cn } from "@/lib/cn";
import { assetName } from "@/lib/names";
import { formatET, formatETOn } from "@/lib/time";
import { ViewDecision } from "../agent-panel/decisionLink";
import type { SourceCite } from "../agent-panel/types";
import { decisionTitle } from "../decisions/actionTypes";
import { useCard, useProposals } from "../decisions/useQueue";
import { type PlatformSource, type SourceSet, sourceCount } from "./sources";

const plainSourceName = (s: PlatformSource): string => {
  const name = s.title ?? (s.id ? assetName(s.id) : s.label);
  return name.charAt(0).toUpperCase() + name.slice(1);
};

const STATUS_WORD = { running: "Working…", ok: "", refused: "Not allowed", error: "Failed" } as const;

function Bar() {
  return <span aria-hidden className="absolute inset-y-0 left-0 w-[3px] bg-blue" />;
}

function DocRow({ c, active }: { c: SourceCite; active: boolean }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (active) ref.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [active]);
  return (
    <article
      ref={ref}
      data-testid="source-card"
      data-active={active}
      className={cn("relative border-b border-hair px-5 py-3", active && "bg-selected")}
    >
      {active && <Bar />}
      <p className="m-0 flex items-center gap-1.5">
        <FileText aria-hidden className="size-3.5 shrink-0 text-muted" />
        <span className="font-mono text-[12px] font-medium break-all text-blue-ink">{c.citationId}</span>
      </p>
      <p className="m-0 mt-1 line-clamp-2 text-[14px] leading-5 font-semibold">{c.section}</p>
      <p className="m-0 text-[12px] text-muted">{c.pages}</p>
      <blockquote
        className={cn(
          "m-0 mt-1.5 text-[13px] leading-[19px] break-words text-ink-2",
          !active && "line-clamp-2",
        )}
      >
        {c.quote}
      </blockquote>
      {c.unverified ? (
        <p className="m-0 mt-1.5 flex items-center gap-1 text-[12px] text-warn">
          Unverified field report, not procedure.
          <InfoTip term="unverified_record" />
        </p>
      ) : (
        <p className="m-0 mt-1.5 text-[12px] text-muted">Current procedure</p>
      )}
    </article>
  );
}

const CASE_ID = /\bDC-[A-Z0-9]+(?:-[A-Z0-9]+)+\b/g;

function PlatformRow({ s, readAt }: { s: PlatformSource; readAt: string | null }) {
  const proposals = useProposals().data;
  const proposalId = s.decisionCaseId
    ? (proposals?.find((p) => p.decision_case_id === s.decisionCaseId)?.proposal_id ?? null)
    : null;
  const card = useCard(proposalId).data;
  const domain = card ? (card.case.domain === "water" ? "water" : "power") : s.domain;
  const heading = card ? decisionTitle(card.title) : plainSourceName(s);
  const titleOf = (caseId: string) => {
    const title = proposals?.find((p) => p.decision_case_id === caseId)?.title;
    if (title) return decisionTitle(title);
    return caseId === s.decisionCaseId ? heading : "another decision";
  };
  const quote = (s.quote ?? "")
    .replace(CASE_ID, (id) => titleOf(id))
    .replace(/^(.+?)\s+\1\b/i, "$1")
    .replace(new RegExp(`^${heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[:\\s]*`, "i"), "");
  const text = quote
    ? quote.charAt(0).toUpperCase() + quote.slice(1)
    : card
      ? `Deadline ${formatETOn(card.effective_decide_by_utc, readAt)}.`
      : null;
  const status = STATUS_WORD[s.status];
  const kind = s.decisionCaseId ? "Decision" : s.label;
  const meta = [kind !== heading && kind, readAt && `read ${formatET(readAt)}`, status]
    .filter(Boolean)
    .join(", ");
  return (
    <article data-testid="platform-source" className="border-b border-hair px-5 py-3">
      <p className="m-0 flex flex-wrap items-center gap-x-2 gap-y-0.5">
        {domain && <DomainMark domain={domain} />}
        <span className="text-[13px] font-medium">{heading}</span>
      </p>
      <p className="m-0 mt-0.5 text-[12px] text-muted">{meta}</p>
      {text && <p className="m-0 mt-1 text-[13px] leading-[19px] text-ink-2">{text}</p>}
      {proposalId && (
        <p className="m-0 mt-1.5">
          <ViewDecision id={proposalId} />
        </p>
      )}
    </article>
  );
}

interface ListProps {
  sources: SourceSet;
  activeN: number | null;
  readAt: string | null;
}

export function SourcesList({ sources, activeN, readAt }: ListProps) {
  const { docs, platform } = sources;
  return (
    <>
      {docs.length > 0 && (
        <section aria-label="Documents">
          <h3 className="m-0 flex items-center gap-1.5 px-5 pt-4 pb-1 text-[12px] font-semibold text-ink-2">
            <DomainMark domain="docs" withLabel />
          </h3>
          {docs.map((c) => (
            <DocRow key={c.n} c={c} active={activeN === c.n} />
          ))}
        </section>
      )}
      {platform.length > 0 && (
        <section aria-label="Platform data">
          <h3 className="m-0 px-5 pt-4 pb-1 text-[12px] font-semibold text-ink-2">Platform data</h3>
          {platform.map((p) => (
            <PlatformRow key={p.key} s={p} readAt={readAt} />
          ))}
        </section>
      )}
    </>
  );
}

interface PanelProps extends ListProps {
  onClose: () => void;
}

/** The right-hand panel: Documents first, then Platform data. Quiet rows on one surface, a 1 px rule between them. */
export function SourcesPanel({ sources, activeN, readAt, onClose }: PanelProps) {
  return (
    <aside id="sources-panel" aria-label="Sources" className="flex h-full min-h-0 w-full flex-col bg-surface">
      <header className="flex h-14 shrink-0 items-center gap-2 px-5">
        <h2 className="m-0 text-[16px] font-bold">Sources</h2>
        <CountBadge count={sourceCount(sources)} />
        <InfoTip term="source_badge" />
        <span className="flex-1" />
        <IconButton tooltipSide="bottom" label="Hide sources" onClick={onClose} icon={<X aria-hidden />} />
      </header>
      <div data-scroll-region="ask-sources" className="min-h-0 flex-1 overflow-y-auto pb-6">
        <SourcesList sources={sources} activeN={activeN} readAt={readAt} />
      </div>
    </aside>
  );
}
