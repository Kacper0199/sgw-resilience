import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { FUNCTION_LABEL, PERSONAS } from "@/auth/personas";
import { useCan } from "@/auth/usePermissions";
import { useMe } from "@/auth/useSession";
import { InfoTip } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { ApprovalFunction } from "@/contracts/vocab.gen";
import { ReasonTip } from "@/features/decisions/ReasonTip";
import { cn } from "@/lib/cn";
import { Failed, Loading } from "./Async";
import { ControlDialog, type ControlKind } from "./ControlDialog";
import { dayTime, humanize, sentence } from "./format";
import { SectionHead } from "./SectionHead";
import { Mark, StatusLine } from "./Status";
import { CAPABILITY_LABEL, KILL_LEVELS, KILL_ORDER } from "./safety";
import { TH } from "./tables";
import type { Capabilities, CapabilityKey, KillLevel } from "./types";
import { useCapabilities } from "./useHealth";

function Summary({ state }: { state: Capabilities | undefined }) {
  if (!state) return <StatusLine tone="idle" headline="Loading SGW mode…" detail="Switches are loading." />;
  if (!state.control_readable)
    return (
      <StatusLine
        tone="bad"
        headline="Couldn't load the stop level."
        detail="To be safe, SGW pauses signing until it loads again."
      />
    );
  const mode = state.mode_ladder.find((m) => m.mode === state.degraded_mode);
  const stopped = state.kill_level !== "K0";
  if (!stopped && state.degraded_mode === "M0" && state.active_signals.length === 0)
    return <StatusLine tone="ok" headline="Normal operation." detail="Nothing is switched off." />;
  const parts = [
    stopped ? `${KILL_LEVELS[state.kill_level].label}.` : "",
    mode && state.degraded_mode !== "M0" ? `Switched off: ${mode.disabled}.` : "",
    state.pending_restore ? "A resume request is waiting for a second team." : "",
    state.active_signals.length
      ? `Cause: ${state.active_signals.map((s) => humanize(s.signal)).join(", ")}.`
      : "",
  ];
  return (
    <StatusLine
      tone={stopped || state.degraded_mode >= "M3" ? "bad" : "warn"}
      headline={`${mode?.name ?? state.degraded_mode}.`}
      detail={parts.filter(Boolean).join(" ")}
    />
  );
}

const SELECTED = "bg-selected shadow-[inset_3px_0_0_var(--blue)]";

function ModeTable({ state, onChange }: { state: Capabilities; onChange: () => void }) {
  const raise = useCan("mode_raise");
  const lower = useCan("mode_lower");
  return (
    <>
      <SectionHead
        title="SGW modes"
        info="degraded_mode"
        actions={
          raise || lower ? (
            <Button variant="secondary" onClick={onChange}>
              Set mode
            </Button>
          ) : null
        }
      />
      <table className="w-full border-collapse text-[14px]">
        <caption className="sr-only">SGW modes</caption>
        <thead>
          <tr>
            <th className={cn(TH, "px-8")}>Mode</th>
            <th className={TH}>Still on</th>
            <th className={cn(TH, "px-8")}>Switched off</th>
          </tr>
        </thead>
        <tbody>
          {state.mode_ladder.map((m) => {
            const now = m.mode === state.degraded_mode;
            return (
              <tr
                key={m.mode}
                aria-current={now ? "true" : undefined}
                data-testid="mode-row"
                className={cn("border-b border-hair", now && SELECTED)}
              >
                <td className="px-8 py-2.5 align-top whitespace-nowrap">
                  <span className="font-medium">{m.name}</span>
                  {now && <span className="ml-2 text-[12px] font-semibold text-blue-ink"> Now</span>}
                </td>
                <td className="px-3 py-2.5 align-top text-[13px]">{sentence(m.available)}</td>
                <td className="px-8 py-2.5 align-top text-[13px] text-muted">{sentence(m.disabled)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {state.active_signals.length > 0 ? (
        <div className="px-8 pt-4" data-testid="signals">
          <p className="m-0 mb-1.5 text-[13px] font-semibold">Why this mode is on</p>
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
            {state.active_signals.map((s) => (
              <li key={s.signal} className="text-[13px]">
                <Mark tone="warn">{humanize(s.signal)}</Mark>
                <span className="text-muted">
                  {" "}
                  since {s.since ? dayTime(s.since) : "unknown"}; clears when{" "}
                  {s.exit.charAt(0).toLowerCase() + s.exit.slice(1)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="m-0 px-8 pt-3 text-[13px] text-muted">No faults.</p>
      )}
    </>
  );
}

function SwitchedOn({ state }: { state: Capabilities }) {
  const [open, setOpen] = useState(false);
  const entries = Object.entries(state.capabilities) as [CapabilityKey, boolean][];
  const off = entries.filter(([, on]) => !on).length;
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="mt-4 border-y border-hair bg-surface-2">
      <CollapsibleTrigger className="flex h-11 w-full items-center gap-2 px-8 text-[13px] font-semibold">
        <ChevronRight
          className={cn("size-4 text-muted transition-transform duration-[160ms]", open && "rotate-90")}
          aria-hidden
        />
        What's on now
        <span className="font-normal text-muted">{off === 0 ? "everything" : `${off} off`}</span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul
          className="m-0 grid list-none gap-x-6 gap-y-2 px-8 pt-1 pb-4 min-[900px]:grid-cols-2"
          data-testid="capabilities"
        >
          {entries.map(([key, on]) => (
            <li key={key} className="flex items-center gap-2 text-[13px]">
              <Mark tone={on ? "ok" : "bad"} className="font-normal">
                <span className={on ? "text-ink" : "text-muted"}>
                  {CAPABILITY_LABEL[key] ?? humanize(key)}
                </span>
              </Mark>
              <span className="sr-only">{on ? "on" : "switched off"}</span>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

function StopLevel({ state, onAct }: { state: Capabilities; onAct: (kind: ControlKind) => void }) {
  const me = useMe().data;
  const pending = state.pending_restore;
  const sameTeam = pending !== null && me?.function === pending.requested_function;
  const canRaise = useCan("stop_raise") && state.kill_level !== "K4";
  const canRestore = useCan("stop_restore") && state.kill_level !== "K0";
  const team = me ? FUNCTION_LABEL[me.function as ApprovalFunction] : "your team";
  return (
    <>
      <SectionHead
        title={
          <>
            Stop: {KILL_LEVELS[state.kill_level].label}
            <ReasonTip label="What each stop level does" title="Stop levels">
              <ol className="m-0 list-none p-0" aria-label="Stop levels">
                {KILL_ORDER.map((k) => (
                  <li
                    key={k}
                    data-testid="kill-level"
                    aria-current={k === state.kill_level ? "true" : undefined}
                    className="py-0.5"
                  >
                    <span className="font-semibold text-ink">{KILL_LEVELS[k].label}</span>
                    {k === state.kill_level ? " (now). " : ". "}
                    {KILL_LEVELS[k].effect}
                  </li>
                ))}
              </ol>
            </ReasonTip>
          </>
        }
        actions={
          <>
            {canRestore && (
              <span className="mr-2 inline-flex items-center gap-1 text-[12px] text-muted">
                Resuming needs two teams
                <InfoTip term="two_function_restore" />
              </span>
            )}
            {canRestore && (
              <Button
                disabled={sameTeam}
                title={sameTeam ? "A different team must sign to resume." : undefined}
                onClick={() => onAct("restore")}
              >
                {pending ? `Sign as ${team}` : "Resume"}
              </Button>
            )}
            {canRaise && (
              <Button variant="destructive" onClick={() => onAct("raise")}>
                Raise stop level
              </Button>
            )}
          </>
        }
      />
      {pending && (
        <div
          className="mx-8 mb-3 border-l-[3px] border-warn-mark bg-surface-2 px-4 py-2.5 text-[13px]"
          data-testid="pending-restore"
        >
          <p className="m-0 font-semibold">
            Resume to {KILL_LEVELS[pending.to_level as KillLevel]?.label ?? pending.to_level} is waiting for a
            second team to sign.
          </p>
          <p className="m-0 mt-0.5 text-muted">
            Signed by{" "}
            {PERSONAS.find((p) => p.user_id === pending.requested_by)?.title ?? pending.requested_by} (
            {FUNCTION_LABEL[pending.requested_function as ApprovalFunction] ??
              humanize(pending.requested_function)}
            ). A different team must sign within 15 minutes of the first signature.
          </p>
        </div>
      )}
    </>
  );
}

export function SafetyTab() {
  const caps = useCapabilities();
  const [dialog, setDialog] = useState<ControlKind | null>(null);
  return (
    <div className="pb-4">
      <Summary state={caps.data} />
      {caps.isPending ? (
        <Loading what="SGW mode" />
      ) : caps.error ? (
        <Failed what="The SGW mode" error={caps.error} />
      ) : (
        <>
          <ModeTable state={caps.data} onChange={() => setDialog("mode")} />
          <SwitchedOn state={caps.data} />
          <StopLevel state={caps.data} onAct={setDialog} />
          {dialog && (
            <ControlDialog
              key={dialog}
              kind={dialog}
              state={caps.data}
              open
              onOpenChange={(o) => !o && setDialog(null)}
            />
          )}
        </>
      )}
    </div>
  );
}
