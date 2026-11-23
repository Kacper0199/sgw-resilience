import { Check } from "lucide-react";
import { cn } from "@/lib/cn";
import type { StepState, ZoneNotice } from "./lifecycle";

const STATE_WORD: Record<StepState, string> = { done: "done", current: "now", todo: "to do" };

const samplesTip = (needed: number | undefined) =>
  needed ? `${needed} clean lab samples are needed to lift the notice` : "Clean lab samples";

/** "Samples 1/2" once the notice is issued and the register counts the clean samples. */
function stepLabel(notice: ZoneNotice, key: string, label: string, state: StepState): string {
  if (key !== "samples" || state === "todo" || notice.samplesNeeded === undefined) return label;
  return `${label} ${Math.min(notice.cleanSamples ?? 0, notice.samplesNeeded)}/${notice.samplesNeeded}`;
}

function Node({ state }: { state: StepState }) {
  return (
    <span
      aria-hidden
      className={cn(
        "relative z-10 grid size-4 place-items-center rounded-full border-2",
        state === "done" && "border-primary bg-primary text-on-primary",
        state === "current" && "border-blue bg-canvas",
        state === "todo" && "border-hair-strong bg-canvas",
      )}
    >
      {state === "done" && <Check className="size-2.5" strokeWidth={3.5} />}
      {state === "current" && <span className="size-1.5 rounded-full bg-blue" />}
    </span>
  );
}

/** The five steps of a boil-water notice in one line: due, issued, samples, lift, lifted. The label under each carries the state in words for screen readers. */
export function NoticeStepper({ notice, zoneLabel }: { notice: ZoneNotice; zoneLabel: string }) {
  return (
    <ol
      className="m-0 grid min-w-0 list-none grid-cols-5 p-0"
      aria-label={`Notice steps for ${zoneLabel}`}
      data-testid="notice-stepper"
      data-current={notice.current}
    >
      {notice.steps.map((step, i) => {
        const reached = step.state !== "todo";
        return (
          <li
            key={step.key}
            data-step={step.key}
            data-state={step.state}
            aria-current={step.state === "current" ? "step" : undefined}
            title={step.key === "samples" ? samplesTip(notice.samplesNeeded) : undefined}
            className="relative flex min-w-0 flex-col items-center gap-1.5"
          >
            {i > 0 && (
              <span
                aria-hidden
                className={cn(
                  "absolute top-[7px] right-1/2 h-0.5 w-full",
                  reached ? "bg-primary" : "bg-hair-strong",
                )}
              />
            )}
            <Node state={step.state} />
            <span
              className={cn(
                "text-[12px] leading-4 whitespace-nowrap",
                step.state === "current" ? "font-semibold text-ink" : "text-muted",
              )}
            >
              {stepLabel(notice, step.key, step.label, step.state)}
              <span className="sr-only"> ({STATE_WORD[step.state]})</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
