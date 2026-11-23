import { ChevronDown } from "lucide-react";
import { Tabs as TabsPrimitive } from "radix-ui";
import * as React from "react";
import { cn } from "@/lib/cn";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "./dropdown-menu";

interface TabsState {
  value: string | undefined;
  select: (value: string) => void;
}

const TabsContext = React.createContext<TabsState>({ value: undefined, select: () => {} });

export function Tabs({
  value,
  defaultValue,
  onValueChange,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Root>) {
  const [inner, setInner] = React.useState(defaultValue);
  const current = value ?? inner;
  const select = React.useCallback(
    (next: string) => {
      setInner(next);
      onValueChange?.(next);
    },
    [onValueChange],
  );
  return (
    <TabsContext.Provider value={{ value: current, select }}>
      <TabsPrimitive.Root value={current} onValueChange={select} {...props} />
    </TabsContext.Provider>
  );
}

const MORE_WIDTH = 76;
const TAB_GAP = 20;

type TriggerElement = React.ReactElement<{ value: string; children?: React.ReactNode; disabled?: boolean }>;

const isTrigger = (node: React.ReactNode): node is TriggerElement =>
  React.isValidElement(node) && typeof (node.props as { value?: unknown }).value === "string";

/** Tabs that do not fit the width move into a "More" menu, so the row never scrolls. */
export function TabsList({ className, children, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  const row = React.useRef<HTMLDivElement>(null);
  const list = React.useRef<HTMLDivElement>(null);
  const { value, select } = React.useContext(TabsContext);
  const [firstHidden, setFirstHidden] = React.useState<number | null>(null);
  const [padRight, setPadRight] = React.useState(0);
  const items = React.Children.toArray(children);

  const measure = React.useCallback(() => {
    const el = row.current;
    if (!el) return;
    const tabs = Array.from(list.current?.querySelectorAll<HTMLElement>(':scope > [role="tab"]') ?? []);
    const style = getComputedStyle(el);
    const pad = Number.parseFloat(style.paddingRight);
    setPadRight(pad);
    const room = el.clientWidth - pad;
    const right = (t: HTMLElement) => t.offsetLeft + t.offsetWidth;
    if (tabs.length === 0 || right(tabs[tabs.length - 1] as HTMLElement) <= room) {
      setFirstHidden(null);
      return;
    }
    const limit = room - MORE_WIDTH - TAB_GAP;
    const index = tabs.findIndex((t) => right(t) > limit);
    setFirstHidden(Math.max(1, index));
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: tabs are re-measured whenever the set of children changes
  React.useLayoutEffect(measure, [measure, items.length]);
  React.useEffect(() => {
    const el = row.current;
    if (!el) return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [measure]);

  const triggers = items.filter(isTrigger);
  const hidden = firstHidden === null ? [] : triggers.slice(firstHidden);
  const activeHidden = hidden.find((t) => t.props.value === value);
  const shown = items.map((node) => {
    if (!isTrigger(node)) return node;
    const index = triggers.indexOf(node);
    const away = firstHidden !== null && index >= firstHidden;
    return away
      ? React.cloneElement(node as React.ReactElement<Record<string, unknown>>, {
          className: cn((node.props as { className?: string }).className, "invisible"),
          inert: true,
          "aria-hidden": true,
        })
      : node;
  });

  return (
    <div
      ref={row}
      className={cn(
        "relative flex items-end gap-5 overflow-hidden border-b border-hair bg-surface",
        className,
      )}
    >
      <TabsPrimitive.List ref={list} className="contents" {...props}>
        {shown}
      </TabsPrimitive.List>
      {hidden.length > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              data-state={activeHidden ? "active" : "inactive"}
              style={{ width: MORE_WIDTH, right: padRight }}
              className={cn(
                "absolute bottom-0 inline-flex h-10 items-center justify-end gap-1 border-b-[3px] border-transparent bg-surface px-0.5 text-[14px] font-medium whitespace-nowrap text-muted",
                "hover:text-ink data-[state=active]:border-blue data-[state=active]:font-semibold data-[state=active]:text-ink",
                "focus-visible:outline-offset-[-2px]",
              )}
              aria-label={`More tabs, ${hidden.length}`}
            >
              More
              <ChevronDown className="size-3.5" aria-hidden />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {hidden.map((t) => (
              <DropdownMenuItem
                key={t.props.value}
                disabled={t.props.disabled}
                onSelect={() => select(t.props.value)}
                className={cn("gap-2", t.props.value === value && "font-semibold")}
              >
                {t.props.children}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}

/**
 * Radix focuses a tab from its own mousedown handler, which Chromium counts as keyboard focus. The pointer marker
 * keeps the focus box for keyboard users only; the box is drawn inside the tab so the clipping list never hides it.
 */
export function TabsTrigger({
  className,
  onPointerDown,
  onKeyDown,
  onBlur,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex h-10 shrink-0 items-center gap-1.5 border-b-[3px] border-transparent px-0.5 text-[14px] font-medium whitespace-nowrap text-muted transition-colors duration-120",
        "hover:text-ink data-[state=active]:border-blue data-[state=active]:font-semibold data-[state=active]:text-ink",
        "focus-visible:outline-offset-[-2px] data-pointer:focus-visible:outline-none",
        className,
      )}
      onPointerDown={(e) => {
        e.currentTarget.dataset.pointer = "";
        onPointerDown?.(e);
      }}
      onKeyDown={(e) => {
        delete e.currentTarget.dataset.pointer;
        onKeyDown?.(e);
      }}
      onBlur={(e) => {
        delete e.currentTarget.dataset.pointer;
        onBlur?.(e);
      }}
      {...props}
    />
  );
}

export function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content className={cn("pt-4 outline-none", className)} {...props} />;
}
