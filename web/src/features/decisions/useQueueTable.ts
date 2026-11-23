import {
  type ColumnFiltersState,
  columnFilteringFeature,
  createColumnHelper,
  createFilteredRowModel,
  createPaginatedRowModel,
  createSortedRowModel,
  type PaginationState,
  rowPaginationFeature,
  rowSortingFeature,
  type SortingState,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { useMemo } from "react";
import {
  compareDecideBy,
  compareSeverity,
  type DomainFilter,
  type OwnerFilter,
  type QueueFilter,
  type QueueRow,
  type SortKey,
  type TimingFilter,
} from "./queueModel";

export const PAGE_SIZE = 20;

const features = tableFeatures({
  rowSortingFeature,
  columnFilteringFeature,
  rowPaginationFeature,
  sortedRowModel: createSortedRowModel(),
  filteredRowModel: createFilteredRowModel(),
  paginatedRowModel: createPaginatedRowModel(),
});

const helper = createColumnHelper<typeof features, QueueRow>();

const equals = (row: { getValue: (id: string) => unknown }, id: string, value: unknown) =>
  value === undefined || row.getValue(id) === value;

const columns = helper.columns([
  helper.accessor((r) => r.severity, {
    id: "severity",
    sortFn: (a, b) => compareSeverity(a.original, b.original),
  }),
  helper.accessor((r) => r.title, { id: "title" }),
  helper.accessor((r) => r.decideByMs, {
    id: "decide",
    sortFn: (a, b) => compareDecideBy(a.original, b.original),
  }),
  helper.accessor((r) => r.owner.label, { id: "owner" }),
  helper.accessor((r) => r.domain, { id: "domain", filterFn: equals }),
  helper.accessor((r) => r.owner.fn, { id: "ownerFn", filterFn: equals }),
  helper.accessor((r) => r.pinned, { id: "mine", filterFn: equals }),
  helper.accessor((r) => r.open, { id: "open", filterFn: equals }),
  helper.accessor((r) => r.verdict, { id: "timing", filterFn: equals }),
  helper.accessor((r) => `${r.title} ${r.caseId} ${r.id}`.toLowerCase(), {
    id: "find",
    filterFn: (row, id, value) => String(row.getValue(id)).includes(String(value ?? "")),
  }),
]);

interface Args {
  rows: QueueRow[];
  filter: QueueFilter;
  domain: DomainFilter;
  owner: OwnerFilter;
  timing: TimingFilter;
  find: string;
  sort: SortKey;
  desc: boolean;
  page: number;
}

/** Sorting, the Domain/Owner/Waiting-on-you filters and the page slice all run inside TanStack Table. */
export function useQueueTable({ rows, filter, domain, owner, timing, find, sort, desc, page }: Args) {
  const sorting = useMemo<SortingState>(() => [{ id: sort, desc }], [sort, desc]);
  const columnFilters = useMemo<ColumnFiltersState>(
    () => [
      { id: "open", value: filter !== "decided" },
      ...(filter === "waiting" ? [{ id: "mine", value: true }] : []),
      ...(domain !== "all" ? [{ id: "domain", value: domain }] : []),
      ...(owner !== "all" ? [{ id: "ownerFn", value: owner }] : []),
      ...(timing !== "all" ? [{ id: "timing", value: timing }] : []),
      ...(find.trim() ? [{ id: "find", value: find.trim().toLowerCase() }] : []),
    ],
    [filter, domain, owner, timing, find],
  );
  const pagination = useMemo<PaginationState>(
    () => ({ pageIndex: Math.max(0, page - 1), pageSize: PAGE_SIZE }),
    [page],
  );

  return useTable({
    features,
    columns,
    data: rows,
    getRowId: (r) => r.id,
    state: { sorting, columnFilters, pagination },
    autoResetPageIndex: false,
    enableSortingRemoval: false,
  });
}
