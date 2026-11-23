import { ListChecks } from "lucide-react";
import { useMemo } from "react";
import { CountBadge } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import type { LocalThread } from "../agent-panel/localHistory";

interface Props {
  threads: LocalThread[];
  currentId: string | null;
  activityCount: number;
  onOpen: (id: string) => void;
  onActivity: () => void;
}

const sameDay = (iso: string, now: Date) => {
  const d = new Date(iso);
  return (
    d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
  );
};

/** Chats on this device in two groups; the current chat has the navy bar. Closed until the left icon opens it. */
export function HistoryPanel({ threads, currentId, activityCount, onOpen, onActivity }: Props) {
  const groups = useMemo(() => {
    const now = new Date();
    const today = threads.filter((t) => sameDay(t.createdAt, now));
    const earlier = threads.filter((t) => !sameDay(t.createdAt, now));
    return [
      { name: "Today", items: today },
      { name: "Earlier in this event", items: earlier },
    ].filter((g) => g.items.length > 0);
  }, [threads]);

  return (
    <aside
      id="history-panel"
      aria-label="Chat history"
      className="flex h-full min-h-0 w-full flex-col bg-surface"
    >
      <div data-scroll-region="ask-history" className="min-h-0 flex-1 overflow-y-auto py-3">
        {groups.length === 0 && <p className="m-0 px-5 py-2 text-[13px] text-muted">No chats yet.</p>}
        {groups.map((g) => (
          <section key={g.name} aria-label={g.name}>
            <h2 className="m-0 px-5 pt-3 pb-1 text-[12px] font-semibold text-muted">{g.name}</h2>
            {g.items.map((t) => {
              const current = t.threadId === currentId;
              return (
                <button
                  key={t.threadId}
                  type="button"
                  aria-current={current || undefined}
                  onClick={() => onOpen(t.threadId)}
                  className={cn(
                    "relative block w-full truncate px-5 py-2 text-left text-[14px] hover:bg-surface-2",
                    current && "bg-selected font-semibold",
                  )}
                >
                  {current && <span aria-hidden className="absolute inset-y-0 left-0 w-[3px] bg-primary" />}
                  {t.title}
                </button>
              );
            })}
          </section>
        ))}
      </div>
      <div className="shrink-0 border-t border-hair px-3 py-2">
        <Button variant="tertiary" size="sm" onClick={onActivity} className="gap-1.5">
          <ListChecks aria-hidden />
          Activity
          {activityCount > 0 && <CountBadge count={activityCount} />}
        </Button>
      </div>
    </aside>
  );
}
