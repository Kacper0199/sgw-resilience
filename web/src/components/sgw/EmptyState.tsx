import type { LucideIcon } from "lucide-react";
import type * as React from "react";
import { cn } from "@/lib/cn";

interface EmptyStateProps {
  icon: LucideIcon;
  /** One bold line that says what is missing. */
  title: string;
  /** One grey line that says what to do. */
  description?: string;
  action?: React.ReactNode;
  className?: string;
  role?: "status" | "alert";
}

/** An icon, one bold line, one grey line and at most one action. */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
  role = "status",
}: EmptyStateProps) {
  return (
    <div
      role={role}
      className={cn("flex flex-col items-center justify-center gap-2 px-6 py-12 text-center", className)}
    >
      <Icon className="mb-1 size-6 text-muted" strokeWidth={1.5} aria-hidden />
      <p className="m-0 max-w-sm text-[14px] font-semibold text-ink">{title}</p>
      {description && <p className="m-0 max-w-sm text-[13px] text-muted">{description}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
