import { Check, LoaderCircle, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { toolVerb } from "./labels";
import type { ToolCall } from "./types";

const IDENTIFIER = /^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$/;

/** The first argument of a lookup as raw text: an id, a query or a number. */
export function toolArg(args: Record<string, unknown>): string {
  const first = Object.values(args).find((v) => typeof v === "string" || typeof v === "number");
  return first === undefined ? "" : String(first);
}

/** The argument worth showing a person: a search phrase or a plain name; an identifier gives an empty string. */
export function plainToolArg(args: Record<string, unknown>): string {
  const arg = toolArg(args);
  return IDENTIFIER.test(arg) ? "" : arg;
}

const STATE = {
  running: "Working…",
  ok: "Done",
  refused: "Not allowed",
  error: "Failed",
} as const;

/** One lookup as a small chip: what it did in words, its search phrase muted, the active one outlined. */
export function ToolChip({ call }: { call: ToolCall }) {
  const arg = plainToolArg(call.args);
  const Icon = call.status === "running" ? LoaderCircle : call.status === "ok" ? Check : X;
  return (
    <span
      data-testid="tool-chip"
      className={cn(
        "inline-flex h-6 max-w-full items-center gap-1.5 rounded-sm px-2 text-[12px]",
        call.status === "running" ? "bg-surface ring-1 ring-primary" : "bg-subtle",
        (call.status === "refused" || call.status === "error") && "text-error",
      )}
    >
      <Icon
        aria-hidden
        className={cn("size-3 shrink-0", call.status === "running" && "motion-safe:animate-spin")}
      />
      <span>{toolVerb(call.tool)}</span>
      {arg && <span className="min-w-0 truncate text-muted">{arg}</span>}
      <span className="sr-only">, {STATE[call.status]}</span>
    </span>
  );
}
