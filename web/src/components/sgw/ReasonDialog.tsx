import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { FormField } from "./FormField";

const MIN = 3;

interface ReasonDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirm: string;
  pending?: boolean;
  error?: string | null;
  onConfirm: (reason: string) => void;
  onClose: () => void;
}

/** Confirm a state change with a short reason, which goes into the audit record. */
export function ReasonDialog({
  open,
  title,
  description,
  confirm,
  pending = false,
  error,
  onConfirm,
  onClose,
}: ReasonDialogProps) {
  const [reason, setReason] = useState("");
  useEffect(() => {
    if (open) setReason("");
  }, [open]);
  const ready = reason.trim().length >= MIN;
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="reason-dialog">
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (ready && !pending) onConfirm(reason.trim());
          }}
        >
          <FormField label="Reason" hint="Saved in the audit log." error={error ?? undefined}>
            {(field) => (
              <Textarea
                {...field}
                data-autofocus
                rows={2}
                maxLength={300}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            )}
          </FormField>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose}>
              Back
            </Button>
            <Button type="submit" variant="destructive" disabled={!ready || pending}>
              {confirm}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
