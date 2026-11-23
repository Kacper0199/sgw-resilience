import { TriangleAlert } from "lucide-react";
import { EmptyState, LoadingState } from "@/components/sgw";
import { loadFailureTitle } from "@/lib/loadFailure";

const lower = (what: string) =>
  /^[A-Z][a-z]/.test(what) ? what.charAt(0).toLowerCase() + what.slice(1) : what;

export function Loading({ what }: { what: string }) {
  return <LoadingState rows={3} label={`Loading ${what}…`} className="px-8 py-2" />;
}

export function Failed({ what, error }: { what: string; error?: unknown }) {
  return (
    <EmptyState
      role="alert"
      icon={TriangleAlert}
      title={loadFailureTitle(error, lower(what))}
      className="py-6"
    />
  );
}
