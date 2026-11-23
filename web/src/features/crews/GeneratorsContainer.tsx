import { Zap } from "lucide-react";
import { type DataColumn, DataTable, EmptyState, LoadingState, Section } from "@/components/sgw";
import { NUMBERS } from "@/contracts/numbers.gen";
import { LoadFailed } from "@/features/water/LoadFailed";
import { assetName } from "@/lib/names";
import { formatDuration } from "@/lib/time";
import type { Asset } from "./types";
import { useWaterAssets } from "./useCrews";

const TYPE = (kind: string) => (kind.startsWith("portable") ? "Portable" : "On site");

const COLUMNS: DataColumn<Asset>[] = [
  {
    id: "generator",
    header: "Generator",
    cell: (g) => <span title={g.asset_id}>{assetName(g.asset_id)}</span>,
  },
  { id: "type", header: "Type", cell: (g) => TYPE(g.kind) },
  {
    id: "serves",
    header: "Serves",
    cell: (g) => (g.critical_facility ? "Critical facility" : "Pump station"),
  },
];

/** Generators with the two lead times that set the PS-17 deadlines. */
export function GeneratorsContainer() {
  const q = useWaterAssets();
  const generators = (q.data ?? []).filter((a) => a.kind.includes("generator"));
  return (
    <Section
      title="Generators"
      actions={
        q.data && (
          <span className="text-[13px] text-muted tnum">
            {generators.length} {generators.length === 1 ? "generator" : "generators"}
          </span>
        )
      }
    >
      <dl className="m-0 mb-3 grid grid-cols-2 gap-x-6 text-[13px]">
        <div>
          <dt className="text-[12px] font-semibold text-muted">Hook-up time</dt>
          <dd className="m-0 text-[16px] font-semibold tnum">
            {formatDuration(NUMBERS.demo_ps17_generator_lead_min.value)}
          </dd>
        </div>
        <div>
          <dt className="text-[12px] font-semibold text-muted">Fuel delivery time</dt>
          <dd className="m-0 text-[16px] font-semibold tnum">
            {formatDuration(NUMBERS.demo_ps17_truck_lead_min.value)}
          </dd>
        </div>
      </dl>
      {q.error ? (
        <LoadFailed thing="generators" icon={Zap} error={q.error} onRetry={() => void q.refetch()} />
      ) : q.isPending ? (
        <LoadingState label="Loading generators…" rows={2} />
      ) : generators.length === 0 ? (
        <EmptyState icon={Zap} title="No generators listed." />
      ) : (
        <DataTable
          caption="Generators"
          data={generators}
          columns={COLUMNS}
          getRowId={(g) => g.asset_id}
          compact
          rowTestId="generator-row"
          className="overflow-x-auto [&_tr>:first-child]:pl-0 [&_tr>:last-child]:pr-0"
        />
      )}
    </Section>
  );
}
