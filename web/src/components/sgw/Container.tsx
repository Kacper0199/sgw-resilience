import { AlertTriangle } from "lucide-react";
import type * as React from "react";
import { useId } from "react";
import { ErrorBoundary, type FallbackProps } from "react-error-boundary";
import type { GlossaryKey } from "@/content/glossary";
import { cn } from "@/lib/cn";
import { EmptyState } from "./EmptyState";
import { InfoTip } from "./InfoTip";

interface ContainerProps {
  title: string;
  info?: GlossaryKey;
  /** Short muted text after the title, for example "11 open". */
  count?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  children: React.ReactNode;
}

function Failure({ resetErrorBoundary }: FallbackProps) {
  return (
    <EmptyState
      role="alert"
      icon={AlertTriangle}
      title="Couldn't load this section."
      action={
        <button
          type="button"
          onClick={resetErrorBoundary}
          className="text-[13px] font-medium text-blue-ink hover:underline"
        >
          Try again
        </button>
      }
    />
  );
}

/**
 * A section on the one surface: heading, a 1 px rule, the body. No box, no radius, no shadow. A failure inside stays
 * inside. Kept under its old name so every feature keeps rendering; new pages use PageHeader and Section.
 */
export function Container({
  title,
  info,
  count,
  actions,
  className,
  bodyClassName,
  children,
}: ContainerProps) {
  const id = useId();
  return (
    <section
      aria-labelledby={id}
      className={cn("flex min-h-0 min-w-0 flex-col overflow-hidden bg-surface", className)}
    >
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-hair px-4">
        <span className="inline-flex items-center gap-1">
          <h2 id={id} className="m-0 text-[16px] leading-tight font-bold whitespace-nowrap">
            {title}
          </h2>
          {info && <InfoTip term={info} />}
        </span>
        {count !== undefined && (
          <span className="text-[13px] whitespace-nowrap text-muted tnum">{count}</span>
        )}
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </header>
      <div className={cn("min-h-0 flex-1", bodyClassName)}>
        <ErrorBoundary FallbackComponent={Failure}>{children}</ErrorBoundary>
      </div>
    </section>
  );
}
