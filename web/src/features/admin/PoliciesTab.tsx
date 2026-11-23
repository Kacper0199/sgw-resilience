import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import {
  type DataColumn,
  DataTable,
  DataTableToolbar,
  EmptyState,
  InfoTip,
  SourceLine,
} from "@/components/sgw";
import { policyName } from "./format";
import { LoadState } from "./parts";
import { plainPolicySource } from "./policySource";
import type { PolicyParam } from "./types";
import { usePolicies } from "./useAdmin";

const valueText = (p: PolicyParam): string => `${p.value} ${p.unit}`.trim();

/** Link target for a policy chip anywhere in the app: `/admin?tab=policies&key=<policy key>`. */
export const policyHref = (key: string): string => `/admin?tab=policies&key=${encodeURIComponent(key)}`;

const columns: DataColumn<PolicyParam>[] = [
  {
    id: "setting",
    header: "Setting",
    cell: (p) => (
      <>
        <span className="block text-[14px] leading-[18px] font-medium">{policyName(p.key)}</span>
        <span className="block font-mono text-[12px] text-muted">{p.key}</span>
      </>
    ),
  },
  { id: "value", header: "Value", className: "whitespace-nowrap tnum", cell: valueText },
  { id: "source", header: "Source", className: "text-muted", cell: plainPolicySource },
];

export function PoliciesTab({ selectedKey }: { selectedKey: string | null }) {
  const policies = usePolicies();
  const [filter, setFilter] = useState("");
  const found = selectedKey !== null && policies.data?.some((p) => p.key === selectedKey);

  useEffect(() => {
    if (found)
      document
        .querySelector(`[data-row-id="${CSS.escape(selectedKey)}"]`)
        ?.scrollIntoView({ block: "center" });
  }, [found, selectedKey]);

  if (policies.isPending || policies.isError) return <LoadState query={policies} what="policy settings" />;
  const q = filter.trim().toLowerCase();
  const rows = policies.data.filter(
    (p) =>
      p.key === selectedKey ||
      !q ||
      `${p.key} ${policyName(p.key)} ${plainPolicySource(p)}`.toLowerCase().includes(q),
  );
  return (
    <div className="flex flex-col">
      <DataTableToolbar
        search={filter}
        onSearch={setFilter}
        searchLabel="Search settings"
        placeholder="Search settings"
      >
        <span className="inline-flex items-center gap-1 text-[13px] text-muted">
          SGW's own settings, not legal limits.
          <InfoTip term="policy_param" />
        </span>
      </DataTableToolbar>
      {selectedKey && !found && (
        <p role="status" className="m-0 px-8 pb-2 text-[13px] text-muted" data-testid="policy-missing">
          No setting with that name: <span className="font-mono text-[12px]">{selectedKey}</span>.
        </p>
      )}
      <div data-testid="policy-table">
        <DataTable
          data={rows}
          columns={columns}
          getRowId={(p) => p.key}
          caption="Policy settings"
          selectedId={selectedKey}
          rowTestId="policy-row"
          edge
          empty={<EmptyState icon={Search} title="No settings match." />}
        />
      </div>
      <SourceLine className="px-8 py-3">Changing a value needs its own decision and signatures.</SourceLine>
    </div>
  );
}
