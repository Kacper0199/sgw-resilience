import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { loadFailure, loadFailureTitle } from "@/lib/loadFailure";
import { EmptyState } from "./EmptyState";

/** Skeleton in the shape of table rows; announced once as busy. */
export function LoadingState({
  rows = 4,
  label = "Loading",
  className,
}: {
  rows?: number;
  label?: string;
  className?: string;
}) {
  return (
    <div role="status" aria-busy="true" aria-label={label} className={cn("flex flex-col", className)}>
      {Array.from({ length: rows }, (_, i) => `row-${i}`).map((key) => (
        <div key={key} className="flex items-center gap-4 border-b border-hair px-3 py-3.5">
          <Skeleton className="h-3.5 w-24" />
          <Skeleton className="h-3.5 flex-1" />
          <Skeleton className="h-3.5 w-20" />
        </div>
      ))}
      <span className="sr-only">{label}</span>
    </div>
  );
}

/** "{Thing} did not load." with a way to retry; with the query's `error`, a 403 reads "You don't have access to …". */
export function ErrorState({
  thing,
  title,
  error,
  onRetry,
  className,
}: {
  thing: string;
  /** Replaces the default "{thing} did not load." sentence, for example "Couldn't load this decision.". */
  title?: string;
  error?: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const noAccess = error !== undefined && loadFailure(error) === "no_access";
  return (
    <EmptyState
      role="alert"
      icon={AlertTriangle}
      title={noAccess ? loadFailureTitle(error, thing.toLowerCase()) : (title ?? `${thing} did not load.`)}
      className={className}
      action={
        onRetry &&
        !noAccess && (
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Try again
          </Button>
        )
      }
    />
  );
}
