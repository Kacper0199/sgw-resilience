import type * as React from "react";
import { PageHeader, SplitPane } from "@/components/sgw";
import { ReadinessTabs } from "./ReadinessTabs";

interface HazardLayoutProps {
  id: "heat" | "wildfire";
  sources?: React.ReactNode;
  summary?: React.ReactNode;
  children: React.ReactNode;
  action?: React.ReactNode;
}

/** The Readiness list + detail template for a hazard: header and tabs, key numbers, chart and table; the recommended action in the detail pane. */
export function HazardLayout({ id, sources, summary, children, action }: HazardLayoutProps) {
  return (
    <SplitPane
      id={`readiness-${id}`}
      stackBelow={1280}
      mainMinSize={480}
      end={
        action
          ? {
              label: "Resize recommended action",
              defaultSize: "34%",
              minSize: 320,
              maxSize: "50%",
              content: (
                <aside aria-label="Recommended action" data-testid={`${id}-action`}>
                  {action}
                </aside>
              ),
            }
          : null
      }
    >
      <div className="min-w-0 pb-6" data-testid={`${id}-view`}>
        <PageHeader title="Readiness" info="readiness" actions={sources} />
        <ReadinessTabs />
        {summary}
        {children}
      </div>
    </SplitPane>
  );
}

export function Summary({ children, testId }: { children: React.ReactNode; testId: string }) {
  return (
    <div
      data-testid={testId}
      className="flex flex-wrap items-baseline gap-x-5 gap-y-1 border-b border-hair px-8 pt-2.5 pb-2.5 text-[15px]"
    >
      {children}
    </div>
  );
}

export function BlockHeading({ title, tag }: { title: string; tag: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 px-8 pt-2.5 pb-1">
      <h2 className="m-0 text-[14px] leading-5 font-semibold">{title}</h2>
      {tag}
    </div>
  );
}

export function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[12px] text-muted">{label}</dt>
      <dd className="m-0 text-[14px] font-semibold">{children}</dd>
    </div>
  );
}
