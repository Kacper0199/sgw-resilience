import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useMe } from "@/auth/useSession";
import { EmptyState, InfoTip, Section } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { agentApi } from "../agent-panel/api";
import { PlanChecklist } from "../agent-panel/PlanChecklist";
import { startErrorMessage, useAgentRuns } from "../agent-panel/useAgentRuns";
import { useEtr } from "../etr/useEtr";
import { briefApi } from "./api";
import { SitrepDocView } from "./SitrepDocView";
import type { Brief } from "./types";
import { BRIEF_KEY } from "./useBrief";

const READ_ONLY = new Set(["executive", "audit"]);

export function SitrepContainer({ sitrep }: { sitrep: Brief["sitrep"] }) {
  const qc = useQueryClient();
  const fn = useMe().data?.function;
  const [problem, setProblem] = useState<string | null>(null);
  const [steps, setSteps] = useState(false);
  const live = useAgentRuns(() => void qc.invalidateQueries({ queryKey: BRIEF_KEY }));
  const running = Object.values(live.runs).find((r) => r.status === "running") ?? null;
  const shown = Object.values(live.runs).sort(
    (a, b) => Date.parse(b.startedAt ?? "") - Date.parse(a.startedAt ?? ""),
  )[0];

  const draft = useMutation({
    mutationFn: async () => {
      const thread = await agentApi.createThread("brief", "Situation report");
      const run = await live.start({
        threadId: thread.thread_id,
        graph: "sitrep",
        input: {},
        question: null,
      });
      if (!run) throw new Error("not started");
    },
    onMutate: () => setProblem(null),
    onError: (err) => {
      if (!(err instanceof Error && err.message === "not started")) setProblem(startErrorMessage(err));
    },
  });

  const promote = useMutation({
    mutationFn: (runId: string) => briefApi.promote(runId),
    onMutate: () => setProblem(null),
    onSuccess: () => {
      toast.success("Confirmed. This is now the current situation report.");
      return qc.invalidateQueries({ queryKey: BRIEF_KEY });
    },
    onError: (err) =>
      setProblem(
        err instanceof ApiError && err.status === 403
          ? "Your role can't confirm this report."
          : "The report couldn't be confirmed.",
      ),
  });

  const canPromote = fn !== undefined && sitrep.promote_by.includes(fn);
  const etr = useEtr().data;
  const noEstimate = etr !== undefined && etr.issued_at === null;
  const canDraft = fn !== undefined && !READ_ONLY.has(fn) && !noEstimate;
  const error = problem ?? live.startError;

  return (
    <Section
      title="Situation report"
      info="sitrep"
      actions={
        canDraft ? (
          <Button size="sm" onClick={() => draft.mutate()} disabled={Boolean(running) || draft.isPending}>
            <FileText aria-hidden />
            {running ? "Drafting…" : "Draft a report"}
          </Button>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-3">
        {running && (
          <section aria-live="polite" aria-label="Drafting report…" data-testid="sitrep-progress">
            <p className="m-0 mb-2 text-[13px] font-semibold">Drafting report…</p>
            <PlanChecklist run={running} />
          </section>
        )}
        {!running && shown?.status === "error" && (
          <p role="alert" className="m-0 text-[14px] text-crit">
            {shown.error}
          </p>
        )}
        {sitrep.draft && (
          <SitrepDocView doc={sitrep.draft} label="Draft, waiting for confirmation" draft>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="primary"
                disabled={!canPromote || promote.isPending}
                onClick={() => promote.mutate(sitrep.draft?.run_id ?? "")}
              >
                {promote.isPending ? "Confirming…" : "Confirm report"}
              </Button>
              <InfoTip term="promote" />
              {shown && (
                <Button variant="tertiary" onClick={() => setSteps((o) => !o)} aria-expanded={steps}>
                  {steps ? "Hide steps" : "Show steps"}
                </Button>
              )}
            </div>
            {steps && shown && <PlanChecklist run={shown} />}
            <p className="m-0 text-[13px] text-muted">
              {canPromote
                ? "AI drafted this. Every number has a named source. One person must confirm it. Nothing is sent outside SGW."
                : "Only the Incident Commander can confirm a draft."}
            </p>
          </SitrepDocView>
        )}
        {sitrep.current && <SitrepDocView doc={sitrep.current} label="Current report" draft={false} />}
        {!sitrep.current && !sitrep.draft && !running && (
          <EmptyState
            icon={FileText}
            title={
              noEstimate
                ? "No situation report yet. One can be drafted once a restoration estimate is published."
                : "No situation report yet. Draft one for a person to confirm."
            }
          />
        )}
        {error && (
          <p role="alert" className="m-0 text-[14px] text-crit">
            {error}
          </p>
        )}
      </div>
    </Section>
  );
}
