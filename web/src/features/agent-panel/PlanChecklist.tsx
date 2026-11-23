import { Check, Circle, LoaderCircle } from "lucide-react";
import { cn } from "@/lib/cn";
import { PLANS, type PlanStep } from "./labels";
import type { RunView } from "./types";

type StepState = "done" | "running" | "todo";

function stateOf(run: RunView, step: PlanStep): StepState {
  if (step.looksUp && run.tools.length > 0 && run.tools.every((t) => t.status !== "running")) return "done";
  const states = step.nodes.map((n) => run.nodes.find((x) => x.node === n)?.status);
  if (states.every((s) => s === "done")) return "done";
  if (states.some((s) => s === "running" || s === "done")) return "running";
  return "todo";
}

export function PlanChecklist({ run }: { run: RunView }) {
  const plan = PLANS[run.graph] ?? [];
  if (plan.length === 0) return null;
  return (
    <ol className="m-0 flex list-none flex-col gap-1.5 p-0 text-[13px]" aria-label="Plan">
      {plan.map((step) => {
        const state =
          run.status !== "running" && run.status !== "paused"
            ? stateOf(run, step) === "todo"
              ? "todo"
              : "done"
            : stateOf(run, step);
        const Icon = state === "done" ? Check : state === "running" ? LoaderCircle : Circle;
        return (
          <li key={step.label} className="flex items-start gap-2" data-state={state}>
            <Icon
              aria-hidden
              className={cn(
                "mt-0.5 size-3.5 shrink-0",
                state === "done" ? "text-ok" : "text-muted",
                state === "running" && "motion-safe:animate-spin",
              )}
            />
            <span className={cn(state === "todo" && "text-muted")}>
              {step.label}
              <span className="sr-only">
                {state === "done" ? ", done" : state === "running" ? ", working" : ", skipped"}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
