import { cn } from "@/lib/cn";

/** Muted provenance, for example "Model OUT-2, synthetic input". */
export function SourceLine({ children, className }: { children: string; className?: string }) {
  return <p className={cn("m-0 text-label text-muted", className)}>{children}</p>;
}
