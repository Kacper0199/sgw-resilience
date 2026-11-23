import { OctagonAlert, ScrollText } from "lucide-react";
import { useState } from "react";
import { EmptyState } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { plainIds } from "@/lib/names";
import { formatDayET, formatET, formatZ } from "@/lib/time";
import { count, entryLabels, kindLabel, personaTitle, subjectId } from "./format";
import { DecisionName } from "./parts";
import type { ChainCheck, TimelineEntry } from "./types";

const PAGE = 40;

export function TimelineTab({ entries, chain }: { entries: TimelineEntry[]; chain: ChainCheck }) {
  const [limit, setLimit] = useState(PAGE);
  if (entries.length === 0) return <EmptyState icon={ScrollText} title="No decisions recorded yet." />;
  const ordered = [...entries].sort((a, b) => a.seq - b.seq);
  const shown = ordered.slice(0, limit);
  const labels = entryLabels(ordered);
  return (
    <div className="flex flex-col gap-3">
      {!chain.ok && chain.first_bad_seq !== null && (
        <p role="alert" className="m-0 text-[13px] font-medium text-crit" data-testid="untrusted-note">
          Entries from {count(chain.first_bad_seq)} on fail the check and can't be trusted.
        </p>
      )}
      <ol className="m-0 list-none p-0" data-testid="timeline">
        {shown.map((e, i) => {
          const untrusted = !chain.ok && chain.first_bad_seq !== null && e.seq >= chain.first_bad_seq;
          const newDay =
            i === 0 || formatDayET(shown[i - 1]?.occurred_at ?? "") !== formatDayET(e.occurred_at);
          const subject = subjectId(e.subject);
          return (
            <li
              key={e.seq}
              data-testid="timeline-row"
              data-untrusted={untrusted}
              className={cn("border-b border-hair", untrusted && "bg-crit-soft")}
            >
              {newDay && (
                <p className="m-0 border-b border-hair bg-surface-2 px-3 py-2 text-[13px] font-semibold text-ink-2">
                  {formatDayET(e.occurred_at)}
                </p>
              )}
              <div className="grid min-h-11 grid-cols-[84px_minmax(0,1fr)_auto] items-center gap-x-3 px-3 py-2 text-[14px]">
                <span className="font-mono text-[12px] text-muted tnum">
                  {formatET(e.occurred_at)}
                  <span className="block text-[11px]">{formatZ(e.occurred_at)}</span>
                </span>
                <span className="min-w-0">
                  <span className="font-medium">{labels.get(e.seq) ?? kindLabel(e.kind)}</span>
                  <span className="text-muted">
                    {" "}
                    by {personaTitle(e.actor_id)}, for{" "}
                    {subject.startsWith("PRP-") ? <DecisionName proposalId={subject} /> : plainIds(subject)}
                  </span>
                  {untrusted && (
                    <span className="ml-2 inline-flex items-center gap-1 text-[12px] font-semibold text-crit">
                      <OctagonAlert className="size-3.5" aria-hidden />
                      Not trusted
                    </span>
                  )}
                </span>
                <span className="font-mono text-[11px] text-muted tnum">#{count(e.seq)}</span>
              </div>
            </li>
          );
        })}
      </ol>
      {ordered.length > limit && (
        <div>
          <Button variant="secondary" size="sm" onClick={() => setLimit((l) => l + PAGE)}>
            Show more ({ordered.length - limit} left)
          </Button>
        </div>
      )}
    </div>
  );
}
