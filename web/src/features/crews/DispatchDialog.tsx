import { ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";
import { FormField } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { decisionTitle } from "@/features/decisions/actionTypes";
import { crewName } from "@/lib/names";
import { BLOCK_REASON, type BlockReason, type CrewTarget, useCrewTargets, useDispatch } from "./dispatch";

export type DialogMode = "assign" | "block" | "reject";

interface Props {
  crewId: string;
  mode: DialogMode | null;
  onClose: () => void;
}

const keyOf = (t: Pick<CrewTarget, "kind" | "target_id">) => `${t.kind}:${t.target_id}`;
const REASONS = Object.keys(BLOCK_REASON) as BlockReason[];

function Select({ children, ...props }: React.ComponentProps<"select">) {
  return (
    <span className="relative block">
      <select
        className="h-[34px] w-full cursor-pointer appearance-none rounded-md border border-hair-strong bg-surface pr-9 pl-3 text-[14px] text-ink outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue"
        {...props}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute top-2 right-2.5 size-4 text-muted" aria-hidden />
    </span>
  );
}

/** The one dispatch dialog: assign a crew to an open decision or a staging yard, or say why it is blocked. */
export function DispatchDialog({ crewId, mode, onClose }: Props) {
  const targets = useCrewTargets(mode === "assign");
  const dispatch = useDispatch(crewId);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState<BlockReason>("road_closed");
  const [note, setNote] = useState("");
  useEffect(() => {
    if (mode) {
      setTarget("");
      setReason("road_closed");
      setNote("");
    }
  }, [mode]);
  const list = targets.data ?? [];
  const decisions = list.filter((t) => t.kind === "decision");
  const yards = list.filter((t) => t.kind === "yard");
  const chosen = list.find((t) => keyOf(t) === target);
  const assign = mode === "assign";
  const reject = mode === "reject";
  const submit = () => {
    if (assign && !chosen) return;
    if (reject && !note.trim()) return;
    dispatch.mutate(
      assign && chosen
        ? { kind: "assign", target: chosen }
        : reject
          ? { kind: "reject", note: note.trim() }
          : { kind: "block", reason },
      { onSuccess: onClose },
    );
  };
  return (
    <Dialog open={mode !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="dispatch-dialog">
        <DialogTitle>
          {assign
            ? `Assign ${crewName(crewId)}`
            : reject
              ? `Reject the assignment of ${crewName(crewId)}`
              : `Mark ${crewName(crewId)} blocked`}
        </DialogTitle>
        <DialogDescription>
          {assign
            ? "A second person signs before the crew moves."
            : reject
              ? "The crew stays available. The person who assigned it sees your reason."
              : "The crew stays blocked until you clear it."}
        </DialogDescription>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          {assign ? (
            <FormField
              label="Assign to"
              error={targets.error ? "The list didn't load. Close and try again." : undefined}
            >
              {(field) => (
                <Select
                  {...field}
                  data-autofocus
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  disabled={targets.isPending}
                >
                  <option value="" disabled>
                    {targets.isPending ? "Loading…" : "Choose a decision or a yard"}
                  </option>
                  {decisions.length > 0 && (
                    <optgroup label="Open decisions">
                      {decisions.map((t) => (
                        <option key={keyOf(t)} value={keyOf(t)}>
                          {decisionTitle(t.label)}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  <optgroup label="Staging yards">
                    {yards.map((t) => (
                      <option key={keyOf(t)} value={keyOf(t)}>
                        {t.label}
                      </option>
                    ))}
                  </optgroup>
                </Select>
              )}
            </FormField>
          ) : reject ? (
            <FormField label="Reason">
              {(field) => (
                <Textarea {...field} data-autofocus value={note} onChange={(e) => setNote(e.target.value)} />
              )}
            </FormField>
          ) : (
            <FormField label="Reason">
              {(field) => (
                <Select
                  {...field}
                  data-autofocus
                  value={reason}
                  onChange={(e) => setReason(e.target.value as BlockReason)}
                >
                  {REASONS.map((r) => (
                    <option key={r} value={r}>
                      {BLOCK_REASON[r]}
                    </option>
                  ))}
                </Select>
              )}
            </FormField>
          )}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant={reject ? "destructive-solid" : "primary"}
              disabled={dispatch.isPending || (assign && !chosen) || (reject && !note.trim())}
            >
              {assign ? "Assign" : reject ? "Reject" : "Mark blocked"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
