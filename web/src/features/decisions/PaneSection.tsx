import type * as React from "react";
import { useId } from "react";
import { InfoTip } from "@/components/sgw";
import type { GlossaryKey } from "@/content/glossary";
import { cn } from "@/lib/cn";

interface Props {
  title: React.ReactNode;
  info?: GlossaryKey;
  actions?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
}

/** A section of the decision pane: a 15 px bold title, a 1 px rule, the content. No box, no fill. */
export function PaneSection({ title, info, actions, className, children }: Props) {
  const id = useId();
  return (
    <section aria-labelledby={id} className={cn("min-w-0 pb-6", className)}>
      <header className="mb-3 flex items-center gap-2 border-b border-hair pb-2">
        <h4 id={id} className="m-0 flex items-center gap-1 text-[15px] leading-5 font-bold">
          {title}
          {info && <InfoTip term={info} />}
        </h4>
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </header>
      {children}
    </section>
  );
}
