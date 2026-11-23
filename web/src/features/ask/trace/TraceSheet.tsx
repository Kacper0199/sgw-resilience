import { TriangleAlert } from "lucide-react";
import { LoadingState } from "@/components/sgw";
import { Sheet, SheetContent, SheetHeader } from "@/components/ui/sheet";
import { ApiError } from "@/lib/api";
import { formatET } from "@/lib/time";
import { useCanSeeTrace } from "./permission";
import { Timeline } from "./Timeline";
import { TraceTotals } from "./TraceTotals";
import { useRunTrace, useTraceTarget } from "./useTrace";

const COLUMNS = ["Tokens in / out", "Cost", "Time"] as const;

function Note({ children, alert = false }: { children: string; alert?: boolean }) {
  return (
    <p
      role={alert ? "alert" : "status"}
      className="m-0 flex items-start gap-2 px-6 py-5 text-[14px] text-muted"
    >
      {alert && <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />}
      {children}
    </p>
  );
}

function TraceBody({ runId }: { runId: string }) {
  const trace = useRunTrace(runId);
  if (trace.isPending) return <LoadingState rows={6} label="Loading the steps…" className="px-3" />;
  if (trace.error)
    return trace.error instanceof ApiError && (trace.error.status === 403 || trace.error.status === 404) ? (
      <Note>The steps of this answer are not available.</Note>
    ) : (
      <Note alert>Couldn't load the steps.</Note>
    );
  const { phases, totals } = trace.data;
  if (phases.length === 0) return <Note>No steps were recorded for this answer.</Note>;
  return (
    <>
      <TraceTotals totals={totals} />
      <div
        aria-hidden
        className="grid shrink-0 grid-cols-[minmax(0,1fr)_104px_52px_48px] gap-x-2 border-b border-hair px-6 pt-3 pb-1.5 text-[12px] text-ink-2"
      >
        <span />
        {COLUMNS.map((c) => (
          <span key={c} className="text-right">
            {c}
          </span>
        ))}
      </div>
      <section
        data-scroll-region="trace-timeline"
        aria-label="Timeline"
        // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be reachable by keyboard
        tabIndex={0}
        className="min-h-0 flex-1 overflow-y-auto px-6 pt-3 pb-6 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
      >
        <Timeline phases={phases} />
      </section>
    </>
  );
}

/** "How this answer was made": the steps, specialists, tool calls, AI calls and checks of one run, for the people who audit the AI. */
export function TraceSheet() {
  const [runId, setRunId] = useTraceTarget();
  const allowed = useCanSeeTrace();
  const started = useRunTrace(allowed ? runId : null).data?.startedAt;
  return (
    <Sheet open={allowed && runId !== null} onOpenChange={(open) => !open && void setRunId(null)}>
      <SheetContent aria-describedby={undefined} className="w-[min(560px,100vw)]" data-testid="trace-sheet">
        <SheetHeader
          title="How this answer was made"
          description={
            started ? <span title={runId ?? undefined}>Run at {formatET(started)}</span> : undefined
          }
        />
        {runId && <TraceBody runId={runId} />}
      </SheetContent>
    </Sheet>
  );
}
