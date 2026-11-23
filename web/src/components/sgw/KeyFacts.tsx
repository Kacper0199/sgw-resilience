import type * as React from "react";
import type { GlossaryKey } from "@/content/glossary";
import { cn } from "@/lib/cn";
import { InfoTip } from "./InfoTip";

export interface KeyFact {
  label: string;
  value: React.ReactNode;
  info?: GlossaryKey;
}

export function KeyFacts({
  facts,
  className,
  columns,
}: {
  facts: KeyFact[];
  className?: string;
  columns?: string;
}) {
  return (
    <dl
      className={cn("m-0 grid gap-x-4 gap-y-2 border-y border-hair py-3", className)}
      style={{ gridTemplateColumns: columns ?? `repeat(${facts.length}, minmax(0, 1fr))` }}
    >
      {facts.map((f) => (
        <div key={f.label} className="min-w-0">
          <dt className="flex h-5 items-center gap-1 text-label text-muted">
            {f.label}
            {f.info && <InfoTip term={f.info} />}
          </dt>
          <dd className="m-0 mt-0.5 truncate text-[13px] font-medium">{f.value}</dd>
        </div>
      ))}
    </dl>
  );
}
