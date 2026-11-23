import { ChevronRight, FileSearch, type LucideIcon, MessageSquareText } from "lucide-react";
import { StatusIndicator } from "@/components/sgw";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { Delegation } from "./delegations";
import { ToolChip } from "./ToolChip";

const ICON: Record<string, LucideIcon> = { route_intent: MessageSquareText, investigate: FileSearch };

interface Props {
  d: Delegation;
  onSelectCitation?: (citationId: string) => void;
}

/** One working step: a flat row on the page, no box. Name, status, what it was asked, the lookups it made. */
export function DelegationCard({ d, onSelectCitation }: Props) {
  const Icon = ICON[d.id] ?? FileSearch;
  const { findings } = d;
  const has = findings && (findings.evidenceIds.length > 0 || findings.citationIds.length > 0);
  return (
    <section
      aria-label={d.name}
      data-testid="delegation-card"
      data-status={d.status}
      className="border-b border-hair py-2.5 last:border-b-0"
    >
      <header className="flex min-h-6 items-center gap-2">
        <Icon aria-hidden className="size-4 shrink-0 text-muted" />
        <h4 className="m-0 text-[13px] font-semibold">{d.name}</h4>
        <span className="ml-auto">
          {d.status === "done" ? (
            <StatusIndicator status="ok" label="Done" />
          ) : d.status === "running" ? (
            <StatusIndicator status="running" label="Working…" />
          ) : (
            <StatusIndicator status="idle" label="Waiting" />
          )}
        </span>
      </header>
      <div className="mt-1 flex flex-col gap-2 pl-6">
        <p className="m-0 text-[13px] break-words text-muted">{d.task}</p>
        {d.tools.length > 0 && (
          <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0" aria-label="Lookups">
            {d.tools.map((t) => (
              <li key={t.call} className="max-w-full">
                <ToolChip call={t} />
              </li>
            ))}
          </ul>
        )}
        {has && (
          <Collapsible>
            <CollapsibleTrigger className="group inline-flex h-6 items-center gap-1 text-[13px] font-medium text-ink">
              <ChevronRight
                aria-hidden
                className="size-3.5 transition-transform group-data-[state=open]:rotate-90"
              />
              Found
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-1.5 flex flex-col gap-1.5 text-[13px]">
              {findings.evidenceIds.length > 0 && (
                <p className="m-0 text-muted">
                  Opened {findings.evidenceIds.length} platform{" "}
                  {findings.evidenceIds.length === 1 ? "record" : "records"}
                </p>
              )}
              {findings.citationIds.length > 0 && (
                <p className="m-0 flex flex-wrap items-center gap-1.5">
                  <span className="text-muted">Cited</span>
                  {findings.citationIds.map((id) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => onSelectCitation?.(id)}
                      className="rounded-sm bg-blue-soft px-1.5 py-0.5 font-mono text-[11.5px] text-blue-ink hover:bg-blue-line"
                    >
                      {id}
                    </button>
                  ))}
                </p>
              )}
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>
    </section>
  );
}
