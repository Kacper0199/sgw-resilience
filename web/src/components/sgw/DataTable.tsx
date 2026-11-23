import {
  createColumnHelper,
  createSortedRowModel,
  rowSortingFeature,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronRight, Search } from "lucide-react";
import type * as React from "react";
import { Fragment, useId, useState } from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/cn";
import { CountBadge } from "./CountBadge";

const features = tableFeatures({ rowSortingFeature, sortedRowModel: createSortedRowModel() });

export interface DataColumn<T extends object> {
  id: string;
  header: React.ReactNode;
  cell: (row: T) => React.ReactNode;
  /** Makes the column sortable; return a negative, zero or positive number. */
  sort?: (a: T, b: T) => number;
  /** With a controlled `sorting`, marks the header as a sort button; the parent orders `data`. */
  sortable?: boolean;
  align?: "end";
  className?: string;
  /** Extra classes for the header cell only, for example the page-edge padding of the first column. */
  headerClassName?: string;
}

export interface DataGroup {
  id: string;
  label: string;
  tone?: "neutral" | "warn" | "crit";
  /** Starts folded; the note says why, for example "folded because nothing needs attention". */
  folded?: boolean;
  note?: string;
}

interface DataTableProps<T extends object> {
  data: readonly T[];
  columns: readonly DataColumn<T>[];
  getRowId: (row: T) => string;
  /** Accessible table name, read before the rows. */
  caption: string;
  groups?: readonly DataGroup[];
  groupOf?: (row: T) => string;
  selectedId?: string | null;
  /** Click or Enter on a row; also makes rows keyboard focusable. */
  onSelect?: (row: T) => void;
  /** Rows that `onSelect` skips (no focus stop, no hover): they show everything they have inline. */
  selectable?: (row: T) => boolean;
  /** Rows with detail get a chevron cell; return null for rows without it. */
  renderExpanded?: (row: T) => React.ReactNode;
  /** Rows that start open, for example the abnormal ones. */
  defaultExpanded?: (row: T) => boolean;
  toolbar?: React.ReactNode;
  empty?: React.ReactNode;
  compact?: boolean;
  /** Full-width page table: group rows, chevrons and the first and last columns sit on the 32 px page padding (16 on a phone). */
  edge?: boolean;
  /** Tailwind `top-*` class for the sticky header; override when sticky tabs sit above it. */
  stickyTop?: string;
  className?: string;
  rowTestId?: string;
  /** Controlled sorting: the parent orders `data` and gets the clicked column in `onSortingChange`. */
  sorting?: { id: string; desc: boolean };
  onSortingChange?: (id: string) => void;
  /** Ref of the `tbody`, for example for a reorder animation. */
  bodyRef?: React.Ref<HTMLTableSectionElement>;
}

function moveFocus(e: React.KeyboardEvent<HTMLTableRowElement>) {
  const rows = Array.from(
    e.currentTarget.closest("table")?.querySelectorAll<HTMLTableRowElement>("tr[data-row][tabindex]") ?? [],
  );
  const at = rows.indexOf(e.currentTarget);
  const to =
    e.key === "ArrowDown" ? at + 1 : e.key === "ArrowUp" ? at - 1 : e.key === "Home" ? 0 : rows.length - 1;
  const next = rows[Math.max(0, Math.min(rows.length - 1, to))];
  if (next) {
    e.preventDefault();
    next.focus();
  }
}

/**
 * Full-width table on TanStack Table: sortable headers, group rows, a selected row, expandable rows and arrow-key
 * movement between rows. No card around it. Pass `toolbar` for the find field, selects and chips.
 */
export function DataTable<T extends object>({
  data,
  columns,
  getRowId,
  caption,
  groups,
  groupOf,
  selectedId,
  onSelect,
  selectable,
  renderExpanded,
  defaultExpanded,
  toolbar,
  empty,
  compact = false,
  edge = false,
  stickyTop = "top-0",
  className,
  rowTestId,
  sorting: controlledSorting,
  onSortingChange,
  bodyRef,
}: DataTableProps<T>) {
  const [innerSorting, setSorting] = useState<{ id: string; desc: boolean }[]>([]);
  const controlled = controlledSorting !== undefined;
  const sorting = controlled ? [controlledSorting] : innerSorting;
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [unfolded, setUnfolded] = useState<Record<string, boolean>>({});
  const baseId = useId();

  const helper = createColumnHelper<typeof features, T>();
  const defs = helper.columns(
    columns.map((c) =>
      helper.accessor((r) => r as unknown, {
        id: c.id,
        enableSorting: Boolean(c.sort) && !controlled,
        sortFn: (a, b) => c.sort?.(a.original, b.original) ?? 0,
      }),
    ),
  );
  const table = useTable({
    features,
    columns: defs,
    data: data as T[],
    getRowId,
    state: { sorting },
    onSortingChange: setSorting,
    manualSorting: controlled,
  });

  const lead = edge ? "pl-8 max-[819px]:pl-4" : "";
  const trail = edge ? "pr-8 max-[819px]:pr-4" : "";
  const edgeOf = (i: number) => cn(!expandable && i === 0 && lead, i === columns.length - 1 && trail);
  const rows = table.getRowModel().rows.map((r) => r.original);
  const expandable = Boolean(renderExpanded);
  const span = columns.length + (expandable ? 1 : 0);
  const groupList = groups ?? [{ id: "_", label: "" }];
  const firstId = selectedId ?? (rows[0] ? getRowId(rows[0]) : null);

  const isOpen = (row: T) => open[getRowId(row)] ?? defaultExpanded?.(row) ?? false;
  const picks = (row: T) => Boolean(onSelect) && (selectable?.(row) ?? true);
  const activate = (row: T) => {
    if (onSelect) {
      if (picks(row)) onSelect(row);
    } else if (renderExpanded?.(row) != null) setOpen((o) => ({ ...o, [getRowId(row)]: !isOpen(row) }));
  };

  const body = groupList.map((g) => {
    const members = groups && groupOf ? rows.filter((r) => groupOf(r) === g.id) : rows;
    if (groups && members.length === 0) return null;
    const folded = g.folded && !unfolded[g.id];
    return (
      <Fragment key={g.id}>
        {groups && (
          <tr className="border-b border-hair bg-surface-2">
            <th
              scope="colgroup"
              colSpan={span}
              className={cn("px-3 py-2 text-left text-[13px] font-semibold text-ink-2", lead, trail)}
            >
              <button
                type="button"
                aria-expanded={!folded}
                disabled={!g.folded}
                onClick={() => setUnfolded((u) => ({ ...u, [g.id]: !u[g.id] }))}
                className="inline-flex items-center gap-2 disabled:cursor-default"
              >
                {g.folded && (
                  <ChevronRight
                    className={cn(
                      "size-4 text-muted transition-transform duration-[160ms]",
                      !folded && "rotate-90",
                    )}
                    aria-hidden
                  />
                )}
                {g.label}
                <CountBadge count={members.length} tone={g.tone} />
                {folded && g.note && <span className="font-normal text-muted">{g.note}</span>}
              </button>
            </th>
          </tr>
        )}
        {!folded &&
          members.map((row) => {
            const id = getRowId(row);
            const selected = selectedId === id;
            const detail = renderExpanded?.(row);
            const expanded = detail != null && isOpen(row);
            const panelId = `${baseId}-${id}`;
            return (
              <Fragment key={id}>
                <tr
                  data-row=""
                  data-testid={rowTestId}
                  data-row-id={id}
                  aria-current={selected ? "true" : undefined}
                  data-selected={picks(row) ? selected : undefined}
                  tabIndex={picks(row) || expandable ? (id === firstId ? 0 : -1) : undefined}
                  onClick={(e) => {
                    if (!(e.target as Element).closest("a,button,input,select")) activate(row);
                  }}
                  onKeyDown={(e) => {
                    if (e.target !== e.currentTarget) return;
                    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) moveFocus(e);
                    else if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      activate(row);
                    }
                  }}
                  className={cn(
                    "border-b border-hair outline-offset-[-2px]",
                    compact ? "h-11" : "h-14",
                    (picks(row) || expandable) && "cursor-pointer hover:bg-surface-2",
                    (selected || expanded) &&
                      "bg-selected hover:bg-selected [&>td:first-child]:shadow-[inset_3px_0_0_var(--blue)]",
                  )}
                >
                  {expandable && (
                    <td className={cn("w-9 pl-3", edge && "pl-7 max-[819px]:pl-3")}>
                      {detail != null && (
                        <button
                          type="button"
                          aria-expanded={expanded}
                          aria-controls={panelId}
                          aria-label={`${expanded ? "Collapse" : "Expand"} row`}
                          onClick={() => setOpen((o) => ({ ...o, [id]: !expanded }))}
                          className="grid size-6 place-items-center rounded text-muted hover:text-ink"
                        >
                          <ChevronRight
                            className={cn(
                              "size-4 transition-transform duration-[160ms]",
                              expanded && "rotate-90",
                            )}
                            aria-hidden
                          />
                        </button>
                      )}
                    </td>
                  )}
                  {columns.map((c, i) => (
                    <td
                      key={c.id}
                      className={cn(
                        "px-3 py-[9px] align-middle",
                        edgeOf(i),
                        c.align === "end" && "text-end",
                        c.className,
                      )}
                    >
                      {c.cell(row)}
                    </td>
                  ))}
                </tr>
                {expanded && (
                  <tr
                    id={panelId}
                    className="border-b border-hair bg-selected/40 shadow-[inset_3px_0_0_var(--blue)]"
                  >
                    <td
                      colSpan={span}
                      className={cn("px-12 py-4", edge && "pr-8 pl-[68px] max-[819px]:px-4")}
                    >
                      {detail}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
      </Fragment>
    );
  });

  return (
    <div className={cn("min-w-0", className)}>
      {toolbar}
      <table className="w-full border-collapse text-[14px]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {expandable && (
              <th
                scope="col"
                className={cn("sticky z-10 w-9 border-b border-hair-strong bg-surface", stickyTop)}
              >
                <span className="sr-only">Details</span>
              </th>
            )}
            {columns.map((c, ci) => {
              const sorted = sorting[0]?.id === c.id ? (sorting[0]?.desc ? "desc" : "asc") : null;
              const Icon = sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ArrowUpDown;
              return (
                <th
                  key={c.id}
                  scope="col"
                  aria-sort={
                    c.sort || c.sortable
                      ? sorted === "asc"
                        ? "ascending"
                        : sorted === "desc"
                          ? "descending"
                          : "none"
                      : undefined
                  }
                  className={cn(
                    "sticky z-10 h-9 border-b border-hair-strong bg-surface px-3 text-left text-[12px] font-semibold text-muted",
                    stickyTop,
                    edgeOf(ci),
                    c.align === "end" && "text-end",
                    c.headerClassName,
                  )}
                >
                  {c.sort || c.sortable ? (
                    <button
                      type="button"
                      aria-label={
                        controlled
                          ? `Sort by ${typeof c.header === "string" ? c.header.toLowerCase() : c.id}${sorted ? (sorted === "desc" ? ", descending" : ", ascending") : ""}`
                          : undefined
                      }
                      onClick={() =>
                        controlled
                          ? onSortingChange?.(c.id)
                          : setSorting(
                              sorted === "asc" ? [{ id: c.id, desc: true }] : [{ id: c.id, desc: false }],
                            )
                      }
                      className={cn("inline-flex items-center gap-1 hover:text-ink", sorted && "text-ink")}
                    >
                      {c.header}
                      <Icon className="size-3" aria-hidden />
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody ref={bodyRef}>{body}</tbody>
      </table>
      {rows.length === 0 && empty}
    </div>
  );
}

/** Find field plus any selects, chips and a sort menu, in one row above a table. */
export function DataTableToolbar({
  search,
  onSearch,
  searchLabel = "Find",
  placeholder = "Find",
  searchClassName,
  children,
  className,
}: {
  search?: string;
  onSearch?: (value: string) => void;
  searchLabel?: string;
  placeholder?: string;
  /** Width of the find field; the default is 256 px. */
  searchClassName?: string;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      role="toolbar"
      aria-label="Table filters"
      className={cn(
        "flex flex-wrap items-center gap-2 px-8 py-3 max-[819px]:flex-nowrap max-[819px]:overflow-x-auto max-[819px]:px-4 max-[819px]:[&>*]:shrink-0",
        className,
      )}
    >
      {onSearch && (
        <div className={cn("relative w-64 max-w-full", searchClassName)}>
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted"
            aria-hidden
          />
          <Input
            type="search"
            aria-label={searchLabel}
            placeholder={placeholder}
            value={search ?? ""}
            onChange={(e) => onSearch(e.target.value)}
            className="pl-8"
          />
        </div>
      )}
      {children}
    </div>
  );
}
