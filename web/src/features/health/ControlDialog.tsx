import { useState } from "react";
import { toast } from "sonner";
import { PERSONAS } from "@/auth/personas";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { KILL_LEVELS, KILL_ORDER, MODE_ORDER } from "./safety";
import type { Capabilities, DegradedMode, KillLevel } from "./types";
import { useControl } from "./useHealth";

export type ControlKind = "raise" | "restore" | "mode";

interface Props {
  kind: ControlKind;
  state: Capabilities;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const TITLE: Record<ControlKind, string> = {
  raise: "Raise the stop level",
  restore: "Sign to resume",
  mode: "Set the SGW mode",
};

const personTitle = (userId: string) => PERSONAS.find((p) => p.user_id === userId)?.title ?? userId;

const modeName = (state: Capabilities, mode: DegradedMode) =>
  state.mode_ladder.find((m) => m.mode === mode)?.name ?? mode;

export function ControlDialog({ kind, state, open, onOpenChange }: Props) {
  const control = useControl();
  const pending = state.pending_restore;
  const levelIndex = KILL_ORDER.indexOf(state.kill_level);
  const levelOptions: KillLevel[] =
    kind === "raise"
      ? KILL_ORDER.slice(levelIndex + 1)
      : pending
        ? [pending.to_level]
        : KILL_ORDER.slice(0, levelIndex);
  const modeOptions = MODE_ORDER.filter((m) => m !== state.degraded_mode);
  const [choice, setChoice] = useState<string>("");
  const [reason, setReason] = useState("");
  const [password, setPassword] = useState("");
  const [needsPassword, setNeedsPassword] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const options = kind === "mode" ? modeOptions : levelOptions;
  const value = options.includes(choice as never) ? choice : (options[0] ?? "");
  const valid = reason.trim().length >= 3 && value !== "" && (!needsPassword || password !== "");

  const submit = () => {
    setProblem(null);
    const req =
      kind === "mode"
        ? ({
            kind: "mode",
            mode: value as DegradedMode,
            reason: reason.trim(),
            password: needsPassword ? password : undefined,
          } as const)
        : ({
            kind: "kill",
            level: value as KillLevel,
            reason: reason.trim(),
            password: needsPassword ? password : undefined,
          } as const);
    control.mutate(req, {
      onSuccess: (res) => {
        if (kind === "restore" && res.kill_level !== value)
          toast.success("Signed. A different team must sign to finish resuming.");
        else if (kind === "restore") toast.success("Resumed. Both signatures are in the audit log.");
        else if (kind === "raise") toast.success(`Stop level is now ${KILL_LEVELS[res.kill_level].label}.`);
        else toast.success(`SGW mode is now ${modeName(state, res.degraded_mode)}.`);
        setReason("");
        setPassword("");
        setNeedsPassword(false);
        onOpenChange(false);
      },
      onError: (err) => {
        if (!(err instanceof ApiError)) return setProblem("Can't reach SGW. Check your connection.");
        if (err.code === "STEP_UP_REQUIRED") return setNeedsPassword(true);
        if (err.code === "STEP_UP_FAILED") return setProblem("Wrong password.");
        setProblem(err.message);
      },
    });
  };

  const consequence =
    kind === "mode"
      ? state.mode_ladder.find((m) => m.mode === value)?.disabled
      : value
        ? KILL_LEVELS[value as KillLevel]?.effect
        : undefined;

  return (
    <Dialog open={open} onOpenChange={(o) => !control.isPending && onOpenChange(o)}>
      <DialogContent>
        <div>
          <DialogTitle>{TITLE[kind]}</DialogTitle>
          <DialogDescription className="mt-1">
            {kind === "raise" && "This stops part of SGW at once and is written to the audit log."}
            {kind === "restore" &&
              (pending
                ? `${personTitle(pending.requested_by)} asked to lower the stop level to ${KILL_LEVELS[pending.to_level as KillLevel]?.label ?? pending.to_level}. A different team must sign to finish.`
                : "The first signature starts resuming. A different team must sign within 15 minutes.")}
            {kind === "mode" && "Lower modes switch features back on. Only Command can lower the mode."}
          </DialogDescription>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="control-choice">
            {kind === "mode" ? "Mode" : kind === "raise" ? "New stop level" : "Lower to"}
          </Label>
          <select
            id="control-choice"
            value={value}
            disabled={kind === "restore" && pending !== null}
            onChange={(e) => setChoice(e.target.value)}
            className="h-[34px] rounded-lg border border-hair-strong bg-surface px-2 text-[13px] text-ink disabled:opacity-60"
          >
            {options.map((o) => (
              <option key={o} value={o}>
                {kind === "mode" ? modeName(state, o as DegradedMode) : KILL_LEVELS[o as KillLevel].label}
              </option>
            ))}
          </select>
          {consequence && <p className="m-0 text-label text-muted">{consequence}</p>}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="control-reason">Reason</Label>
          <Textarea id="control-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        {needsPassword && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="control-stepup">Enter your password to continue</Label>
            <Input
              id="control-stepup"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
        )}
        {problem && (
          <p role="alert" className="m-0 text-[13px] text-crit">
            {problem}
          </p>
        )}
        <DialogFooter>
          <Button variant="secondary" disabled={control.isPending} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant={kind === "raise" ? "destructive-solid" : "primary"}
            disabled={control.isPending || !valid}
            onClick={submit}
          >
            {control.isPending
              ? "Working…"
              : needsPassword
                ? "Confirm"
                : kind === "raise"
                  ? "Raise stop level"
                  : kind === "restore"
                    ? "Sign to resume"
                    : "Set mode"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
