import type * as React from "react";
import { useId } from "react";
import type { GlossaryKey } from "@/content/glossary";
import { cn } from "@/lib/cn";
import { InfoTip } from "./InfoTip";

interface SectionCardProps {
  title: React.ReactNode;
  info?: GlossaryKey;
  /** "mine" marks the person's own work: the Waiting on you group and the sign-off line. It is a text accent, not a fill. */
  tone?: "tint" | "mine";
  className?: string;
  children?: React.ReactNode;
}

/** An inspector item: a title, a rule and the content. No card, no fill. */
export function SectionCard({ title, info, tone = "tint", className, children }: SectionCardProps) {
  const id = useId();
  return (
    <section aria-labelledby={id} className={cn("pb-3", className)}>
      <h3
        id={id}
        className={cn(
          "m-0 mb-2.5 flex min-h-[30px] items-center gap-1 border-b border-hair pb-1.5 text-[14px] font-semibold",
          tone === "mine" && "text-warn",
        )}
      >
        {title}
        {info && <InfoTip term={info} />}
      </h3>
      {children}
    </section>
  );
}
