import { useMutation, useQueryClient } from "@tanstack/react-query";
import { parseAsString, useQueryState } from "nuqs";
import { useState } from "react";
import { toast } from "sonner";
import { usePermissions } from "@/auth/usePermissions";
import { FormField, SegmentedControl } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, post } from "@/lib/api";
import { calendarDay } from "./model";
import type { ReadinessItem, ReadinessRecord } from "./types";

type Choice = ReadinessRecord["status"];

const CHOICES = [
  { value: "ready", label: "Ready" },
  { value: "not_ready", label: "Not ready" },
  { value: "waived", label: "Waived" },
] as const;

const DONE: Record<Choice, string> = { ready: "ready", not_ready: "not ready", waived: "waived" };
const LINK = /^https?:\/\/\S+$/;

function failure(error: unknown): string {
  if (error instanceof ApiError && error.code === "READINESS_NOT_OWNER")
    return "Only the owner of this check can record its result.";
  return "Couldn't save the result. Try again.";
}

/** True when the signed-in person owns this check (`readiness_record` in `GET /api/me/permissions`). */
export const useMayRecord = (itemId: string): boolean =>
  usePermissions().data?.readiness_record?.includes(itemId) === true;

/** The owner records the check's result, as of the pre-season review the checks are judged at. */
export function RecordResult({ item, review }: { item: ReadinessItem; review: string | null }) {
  const allowed = useMayRecord(item.item_id);
  const qc = useQueryClient();
  const [, setItemParam] = useQueryState("item", parseAsString);
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Choice>("ready");
  const [note, setNote] = useState("");
  const [link, setLink] = useState("");
  const save = useMutation({
    mutationFn: (body: ReadinessRecord) =>
      post<ReadinessItem>(`/api/readiness/${encodeURIComponent(item.item_id)}`, body),
    onSuccess: (_saved, body) => {
      setOpen(false);
      void setItemParam(item.item_id);
      toast.success(`Recorded as ${DONE[body.status]}.`);
      return qc.invalidateQueries({ queryKey: ["readiness"] });
    },
  });
  if (!allowed) return null;
  const linkOk = link.trim() === "" || LINK.test(link.trim());
  const ready = note.trim().length >= 3 && linkOk;
  const begin = () => {
    setStatus(item.status === "ready" ? "not_ready" : "ready");
    setNote("");
    setLink("");
    save.reset();
    setOpen(true);
  };
  return (
    <>
      <Button variant="secondary" size="sm" className="mt-4" onClick={begin}>
        Record result
      </Button>
      <Dialog open={open} onOpenChange={(o) => !o && setOpen(false)}>
        <DialogContent data-testid="record-result-dialog">
          <DialogTitle>Record result</DialogTitle>
          <DialogDescription>
            {review
              ? `Recorded as of the pre-season review, ${calendarDay(review)}. Saved in the audit log.`
              : "Saved in the audit log."}
          </DialogDescription>
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (!ready || save.isPending) return;
              save.mutate({ status, note: note.trim(), evidence_url: link.trim() || null });
            }}
          >
            <SegmentedControl label="Result" value={status} onValueChange={setStatus} options={CHOICES} />
            <FormField label="Note" error={save.error ? failure(save.error) : undefined}>
              {(field) => (
                <Textarea
                  {...field}
                  data-autofocus
                  rows={2}
                  maxLength={300}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
              )}
            </FormField>
            <FormField
              label="Evidence link (optional)"
              error={linkOk ? undefined : "Use a web link (https://…)."}
            >
              {(field) => (
                <Input
                  {...field}
                  type="url"
                  inputMode="url"
                  maxLength={500}
                  placeholder="https://"
                  value={link}
                  onChange={(e) => setLink(e.target.value)}
                />
              )}
            </FormField>
            <DialogFooter>
              <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
                Back
              </Button>
              <Button type="submit" variant="primary" disabled={!ready || save.isPending}>
                {save.isPending ? "Saving…" : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
