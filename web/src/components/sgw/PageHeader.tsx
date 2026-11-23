import { ChevronRight } from "lucide-react";
import type * as React from "react";
import { Link } from "react-router";
import type { GlossaryKey } from "@/content/glossary";
import { cn } from "@/lib/cn";
import { InfoLink } from "./InfoLink";

export interface Crumb {
  label: string;
  to?: string;
}

interface PageHeaderProps {
  breadcrumb?: readonly Crumb[];
  title: string;
  /** Shown after the title in grey: "Decisions (8)". */
  count?: number | string;
  info?: GlossaryKey;
  /** At most one secondary action on the right. */
  actions?: React.ReactNode;
  className?: string;
}

/** Breadcrumb, bold title with count, a plain Info link and at most one action. */
export function PageHeader({ breadcrumb, title, count, info, actions, className }: PageHeaderProps) {
  return (
    <header
      className={cn(
        "px-8 pt-6 pb-4 [@media(max-height:799px)]:pt-4 [@media(max-height:799px)]:pb-2",
        className,
      )}
    >
      {breadcrumb && breadcrumb.length > 0 && (
        <nav aria-label="Breadcrumb" className="mb-1.5">
          <ol className="m-0 flex list-none flex-wrap items-center gap-1 p-0 text-[12px] text-muted">
            {breadcrumb.map((c, i) => (
              <li key={c.label} className="inline-flex items-center gap-1">
                {i > 0 && <ChevronRight className="size-3" aria-hidden />}
                {c.to ? (
                  <Link to={c.to} className="text-blue-ink hover:underline">
                    {c.label}
                  </Link>
                ) : (
                  <span aria-current="page">{c.label}</span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="m-0 flex items-baseline gap-2 text-page font-bold tracking-[-0.01em]">
          {title}
          {count !== undefined && <span className="text-[18px] font-normal text-muted tnum">({count})</span>}
        </h1>
        {info && <InfoLink term={info} className="print:hidden" />}
        {actions && <div className="ml-auto flex items-center gap-2 print:hidden">{actions}</div>}
      </div>
    </header>
  );
}
