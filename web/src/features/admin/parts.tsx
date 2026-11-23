import { AlertTriangle } from "lucide-react";
import { EmptyState, LoadingState } from "@/components/sgw";
import { ApiError } from "@/lib/api";

/** Loading, error and missing-route states shared by every Admin view. */
export function LoadState({
  query,
  what,
}: {
  query: { isPending: boolean; isError: boolean; error: unknown };
  what: string;
}) {
  if (query.isPending) return <LoadingState rows={4} label={`Loading ${what}…`} className="px-8" />;
  const e = query.error;
  const status = e instanceof ApiError ? e.status : 0;
  const title =
    status === 403
      ? `Only platform administrators can see ${what}.`
      : status === 404 || status === 501
        ? `${what.charAt(0).toUpperCase()}${what.slice(1)} aren't available yet.`
        : `Couldn't load ${what}.`;
  return <EmptyState icon={AlertTriangle} title={title} role="alert" />;
}

/** One-line explanation above a view, aligned with the page padding. */
export function Lede({ children }: { children: React.ReactNode }) {
  return <p className="m-0 flex items-center gap-1 px-8 pb-3 text-[13px] text-muted">{children}</p>;
}
