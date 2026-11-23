import { Hammer } from "lucide-react";
import { Link, useLocation } from "react-router";
import { EmptyState, PageHeader } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { GROUP_LABEL, MODULES } from "./modules";

/** A module without a feature yet, or a path that does not exist: header, one empty state, a way back. */
export function ModulePlaceholder() {
  const { pathname } = useLocation();
  const def = MODULES.find((m) => m.path === pathname);
  return (
    <div className="flex min-h-full flex-col">
      <PageHeader
        breadcrumb={[{ label: "SGW", to: "/" }, ...(def ? [{ label: GROUP_LABEL[def.group] }] : [])]}
        title={def?.label ?? "Page not found"}
      />
      <EmptyState
        icon={def?.icon ?? Hammer}
        className="py-20"
        title={def ? `No ${def.label.toLowerCase()} yet.` : "This page doesn't exist."}
        description={def?.summary}
        action={
          <Button variant="tertiary" asChild>
            <Link to="/">Back to Decisions</Link>
          </Button>
        }
      />
    </div>
  );
}
