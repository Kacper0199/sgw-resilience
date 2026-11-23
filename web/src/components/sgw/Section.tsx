import type * as React from "react";
import { useId } from "react";
import type { GlossaryKey } from "@/content/glossary";
import { cn } from "@/lib/cn";
import { InfoTip } from "./InfoTip";

/** A titled block on the surface: heading, rule, body. */
export function Section({
  title,
  info,
  actions,
  className,
  children,
}: {
  title: React.ReactNode;
  info?: GlossaryKey;
  actions?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className={cn("min-w-0", className)}>
      <header className="mb-3 flex items-center gap-2 border-b border-hair pb-2">
        <h2 id={id} className="m-0 flex items-center gap-1 text-[18px] leading-6 font-bold">
          {title}
          {info && <InfoTip term={info} />}
        </h2>
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </header>
      {children}
    </section>
  );
}
