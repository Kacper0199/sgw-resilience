import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, FileText } from "lucide-react";
import { useState } from "react";
import { useMe } from "@/auth/useSession";
import { InfoTip } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { personaTitle } from "../after-action/format";
import { etrApi } from "./api";
import { plainReview, when } from "./format";
import type { AfterActionDraft } from "./types";
import { REVIEW_DRAFTS_KEY, reviewRunning, useReviewDrafts } from "./useEtr";

export const mayDraftReview = (fn: string | undefined, roles: readonly string[] | undefined): boolean =>
  fn === "command" || fn === "audit" || Boolean(roles?.includes("auditor"));

function download(d: AfterActionDraft) {
  const url = URL.createObjectURL(new Blob([d.markdown ?? ""], { type: "text/markdown" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "after-action-review-draft.md";
  a.click();
  URL.revokeObjectURL(url);
}

/** "Review draft" under the status numbers: the Incident Commander or the auditor starts the after-action draft; everyone who may read drafts sees the latest one. */
export function ReviewDraft() {
  const qc = useQueryClient();
  const me = useMe().data;
  const drafts = useReviewDrafts();
  const [problem, setProblem] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const canDraft = mayDraftReview(me?.function, me?.roles);
  const running = reviewRunning(drafts.data);
  const latest = drafts.data?.find((d) => d.status !== "running");

  const start = useMutation({
    mutationFn: etrApi.draftReview,
    onMutate: () => setProblem(null),
    onSuccess: () => qc.invalidateQueries({ queryKey: REVIEW_DRAFTS_KEY }),
    onError: (err) =>
      setProblem(
        err instanceof ApiError && err.code === "RUN_ACTIVE"
          ? "A draft is already being written."
          : "The draft couldn't start.",
      ),
  });

  if (!canDraft && !latest) return null;
  return (
    <section
      aria-label="Review draft"
      data-testid="review-draft"
      className="flex flex-col gap-2 border-b border-hair pb-4"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <h2 className="m-0 flex items-center gap-1 text-[15px] leading-5 font-bold">
          Review draft
          <InfoTip term="review_draft" />
        </h2>
        {running ? (
          <span role="status" className="text-[14px] font-semibold">
            Drafting…
          </span>
        ) : latest ? (
          <span className="text-[13px] text-muted tnum">
            {`${personaTitle(latest.drafted_by)}, as of ${when(latest.as_of_utc ?? latest.started_at)}`}
            {latest.path === "m2" && ", written without AI"}
          </span>
        ) : (
          <span className="text-[13px] text-muted">None yet.</span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {latest?.summary && (
            <Button variant="tertiary" size="sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
              {open ? "Hide text" : "Show text"}
            </Button>
          )}
          {latest?.markdown && (
            <Button variant="secondary" size="sm" onClick={() => download(latest)}>
              <Download aria-hidden />
              Download
            </Button>
          )}
          {canDraft && !running && (
            <Button size="sm" variant="secondary" onClick={() => start.mutate()} disabled={start.isPending}>
              <FileText aria-hidden />
              Draft report
            </Button>
          )}
        </div>
      </div>
      {open && latest?.status === "draft" && latest.summary && (
        <p className="m-0 max-w-[72ch] text-[14px] leading-6" data-testid="review-summary">
          {plainReview(latest.summary, latest.as_of_utc ?? latest.started_at)}
        </p>
      )}
      {latest && latest.status !== "draft" && (
        <p role="alert" className="m-0 text-[14px] text-crit">
          The last draft couldn't be finished.
        </p>
      )}
      {drafts.isError && (
        <p role="alert" className="m-0 text-[14px] text-crit">
          Drafts did not load.
        </p>
      )}
      {problem && (
        <p role="alert" className="m-0 text-[14px] text-crit">
          {problem}
        </p>
      )}
    </section>
  );
}
