import type * as React from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CountBadge } from "./CountBadge";

export interface CountTab {
  value: string;
  label: string;
  count?: number;
  /** Amber or red badge where the count itself is a problem. */
  tone?: "neutral" | "warn" | "crit";
  content: React.ReactNode;
}

interface CountTabsProps {
  tabs: CountTab[];
  value?: string;
  onValueChange?: (value: string) => void;
  defaultValue?: string;
  label: string;
  /** Extra classes for the tab list, for example `sticky top-0` inside a scrolling panel. */
  listClassName?: string;
  /** Extra classes for each tab panel, for example `pt-0` when the panel holds a full-width table. */
  contentClassName?: string;
}

/** One level of tabs under the page header; a count appears as a badge only where it helps. Never nested. */
export function CountTabs({ tabs, label, listClassName, contentClassName, ...rootProps }: CountTabsProps) {
  const first = tabs[0]?.value;
  return (
    <Tabs defaultValue={first} {...rootProps}>
      <TabsList aria-label={label} className={listClassName}>
        {tabs.map((t) => (
          <TabsTrigger key={t.value} value={t.value}>
            {t.label}
            {t.count !== undefined && <CountBadge count={t.count} tone={t.tone} />}
          </TabsTrigger>
        ))}
      </TabsList>
      {tabs.map((t) => (
        <TabsContent key={t.value} value={t.value} className={contentClassName}>
          {t.content}
        </TabsContent>
      ))}
    </Tabs>
  );
}
