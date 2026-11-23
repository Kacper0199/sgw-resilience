import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { useCan } from "@/auth/usePermissions";
import { ReasonDialog } from "@/components/sgw";
import { ApiError, post } from "@/lib/api";
import type { AgentRun } from "./types";

const ACTIVE = new Set<AgentRun["status"]>(["running", "waiting_approval"]);

/** Platform and data stop a run that is stuck, e.g. waiting for a sign-off nobody will give. */
export function CancelRun({ run }: { run: AgentRun }) {
  const allowed = useCan("agent_run_cancel");
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const cancel = useMutation({
    mutationFn: (reason: string) => post(`/api/runs/${encodeURIComponent(run.run_id)}/cancel`, { reason }),
    onSuccess: () => {
      setOpen(false);
      toast.success("Request stopped.");
      return qc.invalidateQueries({ queryKey: ["health", "agent-runs"] });
    },
  });
  if (!allowed || !ACTIVE.has(run.status)) return null;
  const error = cancel.error
    ? cancel.error instanceof ApiError && cancel.error.status === 409
      ? "It already finished."
      : "Couldn't stop it. Try again."
    : null;
  return (
    <>
      <button
        type="button"
        aria-label={`Stop request ${run.run_id}`}
        onClick={() => setOpen(true)}
        className="ml-4 inline-flex h-7 items-center text-[13px] font-semibold text-crit hover:underline"
      >
        Stop
      </button>
      <ReasonDialog
        open={open}
        title="Stop this AI request"
        description="It ends now and will not resume. A decision it already proposed stays open."
        confirm="Stop request"
        pending={cancel.isPending}
        error={error}
        onConfirm={(reason) => cancel.mutate(reason)}
        onClose={() => {
          setOpen(false);
          cancel.reset();
        }}
      />
    </>
  );
}
