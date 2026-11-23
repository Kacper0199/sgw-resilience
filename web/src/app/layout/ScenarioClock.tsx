import { Clock } from "lucide-react";
import { formatDayZ, formatEtZ } from "@/lib/time";
import { useOps } from "@/sse/OpsStreamProvider";
import type { Connection } from "@/sse/reducer";
import { useScenarioNow } from "@/sse/useScenarioNow";

const CONNECTION_LABEL: Record<Connection, string> = {
  idle: "Disconnected",
  connecting: "Connecting…",
  live: "Connected",
  reconnecting: "Reconnecting…",
  stale: "Not updating",
};

export function ScenarioClock() {
  const now = useScenarioNow();
  const { connection } = useOps();
  return (
    <div
      className="inline-flex items-center gap-2 text-[12px] whitespace-nowrap"
      title={now ? `Replay time, ${formatDayZ(now)}` : "Replay time"}
    >
      <Clock className="size-4 text-topbar-muted" aria-hidden />
      <span className="font-mono tnum" data-testid="scenario-clock">
        {now ? formatEtZ(now) : "Loading…"}
      </span>
      <span
        title={`Updates: ${CONNECTION_LABEL[connection]}`}
        data-testid="stream-state"
        className="text-topbar-muted"
      >
        <svg viewBox="0 0 8 8" className="size-2" aria-hidden>
          {connection === "live" ? (
            <circle cx="4" cy="4" r="3" fill="currentColor" />
          ) : (
            <circle cx="4" cy="4" r="2.5" fill="none" stroke="currentColor" strokeDasharray="2 1.5" />
          )}
        </svg>
        <span className="sr-only">{CONNECTION_LABEL[connection]}</span>
      </span>
    </div>
  );
}
