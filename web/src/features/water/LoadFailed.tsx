import type { LucideIcon } from "lucide-react";
import { EmptyState } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { loadFailure, loadFailureTitle } from "@/lib/loadFailure";

/** "Couldn't load {thing}." with a way to retry, or "You don't have access to {thing}." on a 403. */
export function LoadFailed({
  thing,
  icon,
  error,
  onRetry,
}: {
  thing: string;
  icon: LucideIcon;
  error?: unknown;
  onRetry?: () => void;
}) {
  const noAccess = loadFailure(error) === "no_access";
  return (
    <EmptyState
      role="alert"
      icon={icon}
      title={loadFailureTitle(error, thing)}
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
