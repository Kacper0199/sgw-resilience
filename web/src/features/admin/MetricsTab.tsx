import { ExternalLink, Gauge } from "lucide-react";
import { type DataColumn, DataTable, EmptyState, InfoTip, KeyNumberStrip } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { LoadState } from "./parts";
import type { ApiActivity, RouteTiming } from "./types";
import { useSystem } from "./useAdmin";

const count = new Intl.NumberFormat("en-US");
const ms = (v: number | null) => (v === null ? "–" : `${count.format(v)} ms`);

const columns: DataColumn<RouteTiming>[] = [
  { id: "route", header: "Address", cell: (r) => <span className="font-mono text-[12px]">{r.route}</span> },
  { id: "requests", header: "Requests", align: "end", cell: (r) => count.format(r.requests) },
  { id: "typical", header: "Typical", align: "end", cell: (r) => ms(r.typical_ms) },
  { id: "slow", header: "Slowest 1 in 20", align: "end", cell: (r) => ms(r.slow_ms) },
];

function Activity({ api }: { api: ApiActivity }) {
  return (
    <>
      <KeyNumberStrip
        items={[
          { label: "Requests", value: count.format(api.requests), line: "Since the platform started" },
          {
            label: "Server errors",
            value: count.format(api.server_errors),
            tone: api.server_errors > 0 ? "warn" : undefined,
            line:
              api.requests > 0
                ? `${((api.server_errors / api.requests) * 100).toFixed(1)}% of requests`
                : undefined,
          },
          {
            label: "Typical response",
            value: ms(api.typical_ms),
            line: `Latest ${count.format(api.window)}`,
          },
          { label: "Slowest 1 in 20", value: ms(api.slow_ms), line: `Latest ${count.format(api.window)}` },
        ]}
      />
      {api.slowest.length > 0 && (
        <div className="pt-4" data-testid="metrics-routes">
          <DataTable
            compact
            edge
            caption="Slowest addresses"
            data={api.slowest}
            columns={columns}
            getRowId={(r) => r.route}
            rowTestId="metrics-route"
          />
        </div>
      )}
    </>
  );
}

export function MetricsTab() {
  const system = useSystem();
  const missing =
    system.error instanceof ApiError && (system.error.status === 404 || system.error.status === 501);
  if (system.isPending || (system.isError && !missing))
    return <LoadState query={system} what="system status" />;
  const api = system.data?.api ?? null;
  const url = system.data?.obs_profile_up ? system.data.grafana_url : null;
  return (
    <div className="flex flex-col pb-8" data-testid="metrics">
      {api ? (
        <Activity api={api} />
      ) : (
        <EmptyState icon={Gauge} title="No system metrics yet." className="py-6" />
      )}
      {url && (
        <div className="flex items-center gap-1 px-8 pt-4" data-testid="metrics-grafana">
          <Button variant="secondary" asChild>
            <a href={url} target="_blank" rel="noopener noreferrer">
              Open Grafana
              <ExternalLink aria-hidden />
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          </Button>
          <InfoTip term="system_metrics" />
        </div>
      )}
    </div>
  );
}
