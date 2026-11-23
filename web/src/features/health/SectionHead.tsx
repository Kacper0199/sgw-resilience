import type * as React from "react";
import { useId } from "react";
import { InfoTip } from "@/components/sgw";
import type { GlossaryKey } from "@/content/glossary";
import { cn } from "@/lib/cn";

/** Heading of a block that sits above a full-width table: 18 px bold, optional Info, optional one-line note. */
export function SectionHead({
  title,
  info,
  note,
  actions,
  className,
}: {
  title: React.ReactNode;
  info?: GlossaryKey;
  note?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <header className={cn("px-8 pt-8 pb-3", className)}>
      <div className="flex items-center gap-2">
        <h2 id={id} className="m-0 flex items-center gap-1 text-[18px] leading-6 font-bold">
          {title}
          {info && <InfoTip term={info} />}
        </h2>
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </div>
      {note && <p className="m-0 mt-1 text-[13px] text-muted">{note}</p>}
    </header>
  );
}
