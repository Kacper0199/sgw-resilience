import { CircleCheck, CircleX, Clock, Loader, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

export type Status = "running" | "waiting_approval" | "met" | "missed" | "ok" | "idle";

const STATUS: Record<Status, { icon: LucideIcon; label: string; tone: string }> = {
  running: { icon: Loader, label: "Running", tone: "text-ink" },
  waiting_approval: { icon: Clock, label: "Waiting for sign-off", tone: "text-warn" },
  met: { icon: CircleCheck, label: "Met", tone: "text-muted" },
  missed: { icon: CircleX, label: "Missed", tone: "text-crit" },
  ok: { icon: CircleCheck, label: "Normal", tone: "text-muted" },
  idle: { icon: Clock, label: "Idle", tone: "text-muted" },
};

/** Glyph plus text, no border, one or two words. Grey is normal; colour only for what needs attention. */
export function StatusIndicator({
  status,
  label,
  className,
}: {
  status: Status;
  label?: string;
  className?: string;
}) {
  const { icon: Icon, label: defaultLabel, tone } = STATUS[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap text-[13px] font-medium",
        tone,
        className,
      )}
    >
      <Icon className="size-3.5" aria-hidden />
      {label ?? defaultLabel}
    </span>
  );
}
