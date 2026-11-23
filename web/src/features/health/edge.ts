import type { DataColumn } from "@/components/sgw";
import { cn } from "@/lib/cn";

/** Aligns the first and last column of a full-width table with the 32 px page padding of the header above it. */
export function withEdges<T extends object>(columns: DataColumn<T>[]): DataColumn<T>[] {
  const last = columns.length - 1;
  return columns.map((c, i) => ({
    ...c,
    className: cn(c.className, i === 0 && "pl-8", i === last && "pr-8"),
    headerClassName: cn(c.headerClassName, i === 0 && "pl-8", i === last && "pr-8"),
  }));
}
