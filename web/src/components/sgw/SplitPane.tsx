import type * as React from "react";
import {
  Group,
  Panel,
  type PanelImperativeHandle,
  Separator,
  useDefaultLayout,
} from "react-resizable-panels";
import { cn } from "@/lib/cn";
import { useMediaQuery } from "./useMediaQuery";

export interface SplitSide {
  content: React.ReactNode;
  /** Initial size: a number is pixels, "38%" is a share of the whole split. */
  defaultSize: number | string;
  minSize: number | string;
  maxSize: number | string;
  /** Accessible name of the divider next to this pane. */
  label: string;
  panelRef?: React.Ref<PanelImperativeHandle | null>;
  disabled?: boolean;
  onResize?: (inPixels: number) => void;
  /** Layout shell for the pane's own scrolling; false leaves it to the content. */
  scroll?: boolean;
  /** Names the scroll region for the no-scrollbars test; set it only where the content is a genuinely long list. */
  scrollRegion?: string;
}

interface SplitPaneProps {
  /** Persists the sizes under `react-resizable-panels:sgw.<id>`. */
  id: string;
  children: React.ReactNode;
  start?: SplitSide | null;
  end?: SplitSide | null;
  mainMinSize?: number | string;
  /** Viewport width below which the panes stack instead of sitting side by side. */
  stackBelow?: number;
  scrollMain?: boolean;
  mainScrollRegion?: string;
  className?: string;
  mainClassName?: string;
  testId?: string;
  /** Saves only sizes the user dragged, so a size set by the page itself (a collapsed nav) is not remembered. */
  saveUserSizesOnly?: boolean;
}

const storage = {
  getItem: (key: string) => {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem: (key: string, value: string) => {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* storage unavailable */
    }
  },
};

const SCROLL = "h-full min-h-0 overflow-y-auto overflow-x-hidden";

function Divider({ label, disabled }: { label: string; disabled?: boolean }) {
  return (
    <Separator
      aria-label={label}
      disabled={disabled}
      className={cn(
        "group/divider relative z-10 w-px shrink-0 bg-divider outline-none transition-colors duration-100",
        "before:absolute before:top-1/2 before:left-1/2 before:h-8 before:w-[3px] before:-translate-x-1/2 before:-translate-y-1/2 before:rounded-full before:bg-handle before:transition-colors",
        "after:absolute after:inset-y-0 after:left-1/2 after:w-[3px] after:-translate-x-1/2 after:bg-transparent after:transition-colors",
        "data-[separator=hover]:after:bg-blue data-[separator=active]:after:bg-blue focus-visible:after:bg-blue",
        "data-[separator=hover]:before:bg-blue data-[separator=active]:before:bg-blue focus-visible:before:bg-blue",
        "data-[separator=hover]:before:z-10 data-[separator=active]:before:z-10",
        disabled && "pointer-events-none before:hidden",
      )}
    />
  );
}

function pane(side: SplitSide, id: "start" | "end") {
  return (
    <Panel
      id={id}
      defaultSize={side.defaultSize}
      minSize={side.minSize}
      maxSize={side.maxSize}
      groupResizeBehavior="preserve-pixel-size"
      panelRef={side.panelRef}
      onResize={side.onResize ? (size) => side.onResize?.(size.inPixels) : undefined}
      className="min-w-0"
    >
      <div
        className={side.scroll === false ? "h-full min-h-0" : SCROLL}
        data-scroll-region={side.scrollRegion}
      >
        {side.content}
      </div>
    </Panel>
  );
}

/**
 * The one place that puts two panes side by side: a main pane with an optional pane at its start or end, a divider
 * between them that is dragged, moved with the arrow keys and reset by a double click, and the sizes remembered per
 * page. Below `stackBelow` the panes stack in one scrolling column.
 */
export function SplitPane({
  id,
  children,
  start,
  end,
  mainMinSize = 320,
  stackBelow = 1100,
  scrollMain = true,
  mainScrollRegion,
  className,
  mainClassName,
  testId,
  saveUserSizesOnly,
}: SplitPaneProps) {
  const wide = useMediaQuery(`(min-width: ${stackBelow}px)`);
  const panelIds = [start && "start", "primary", end && "end"].filter(Boolean) as string[];
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: `sgw.${id}`,
    panelIds,
    storage,
    onlySaveAfterUserInteractions: saveUserSizesOnly,
  });

  if (!wide) {
    return (
      <div className={cn("flex min-h-full flex-col", className)} data-testid={testId}>
        {start && <div className="border-b border-hair">{start.content}</div>}
        <div className={cn("min-w-0 flex-1", mainClassName)}>{children}</div>
        {end && <div className="border-t border-hair">{end.content}</div>}
      </div>
    );
  }

  return (
    <Group
      id={`sgw.${id}`}
      orientation="horizontal"
      defaultLayout={defaultLayout}
      onLayoutChanged={onLayoutChanged}
      resizeTargetMinimumSize={{ fine: 12, coarse: 24 }}
      className={cn("h-full min-h-0 w-full", className)}
      data-testid={testId}
    >
      {start && pane(start, "start")}
      {start && <Divider label={start.label} disabled={start.disabled} />}
      <Panel id="primary" minSize={mainMinSize} className="min-w-0">
        <div
          className={cn(scrollMain ? SCROLL : "h-full min-h-0", mainClassName)}
          data-scroll-region={scrollMain ? mainScrollRegion : undefined}
        >
          {children}
        </div>
      </Panel>
      {end && <Divider label={end.label} disabled={end.disabled} />}
      {end && pane(end, "end")}
    </Group>
  );
}
