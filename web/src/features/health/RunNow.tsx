import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { useCan } from "@/auth/usePermissions";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { ApiError, post } from "@/lib/api";
import type { PipelineRun } from "./types";

const DONE: Record<PipelineRun["status"], string> = {
  success: "loaded",
  partial: "partly loaded",
  failed: "failed to load",
  running: "is loading",
};

function failure(error: unknown): string {
  if (error instanceof ApiError && error.code === "PIPELINE_RUNS_PAUSED")
    return "Loading is paused at the current stop level or mode.";
  return "Couldn't start the load. Try again.";
}

/** The data and platform teams load one dataset (and what it depends on) on demand. */
export function RunNow({ name, label }: { name: string; label: string }) {
  const allowed = useCan("pipeline_run");
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const run = useMutation({
    mutationFn: () => post<PipelineRun>(`/api/pipeline/assets/${encodeURIComponent(name)}/run`),
    onSuccess: (result) => {
      setOpen(false);
      toast.success(`${label} ${DONE[result.status]}.`);
      return qc.invalidateQueries({ queryKey: ["health"] });
    },
  });
  if (!allowed) return null;
  return (
    <>
      <button
        type="button"
        aria-label={`Load now: ${label}`}
        onClick={() => setOpen(true)}
        className="mr-4 inline-flex h-7 items-center text-[13px] font-semibold text-blue-ink hover:underline"
      >
        Load now
      </button>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          if (o) return;
          setOpen(false);
          run.reset();
        }}
      >
        <DialogContent data-testid="run-now-dialog">
          <DialogTitle>Load {label} now</DialogTitle>
          <DialogDescription>
            Loads new records from its sources. Records already loaded are not repeated. Saved in the audit
            log.
          </DialogDescription>
          {run.error && (
            <p role="alert" className="m-0 text-[13px] text-crit">
              {failure(run.error)}
            </p>
          )}
          <DialogFooter>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Back
            </Button>
            <Button variant="primary" disabled={run.isPending} onClick={() => run.mutate()}>
              {run.isPending ? "Loading…" : "Load now"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
