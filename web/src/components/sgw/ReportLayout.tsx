import type * as React from "react";
import { cn } from "@/lib/cn";

/**
 * The one frame of a reading page: an 820 px column starting on the page padding, with the "On this page" list in a
 * 200 px column to its right from 1100 px up. Briefing and After-action share it so their title, column and list sit
 * at the same place.
 */
export function ReportLayout({
  children,
  contents,
  className,
}: {
  children: React.ReactNode;
  contents?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid w-full grid-cols-[minmax(0,1fr)] gap-x-12 px-8 pb-16 max-[819px]:px-4 min-[1100px]:grid-cols-[minmax(0,820px)_200px]",
        className,
      )}
    >
      <div className="min-w-0">{children}</div>
      {contents}
    </div>
  );
}
