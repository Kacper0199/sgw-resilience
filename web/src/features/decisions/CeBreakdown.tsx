import { POLICIES } from "@/contracts/policies.gen";
import type { Asset, ProposalCard } from "@/lib/api";
import { assetName } from "@/lib/names";
import { useAssetIndex } from "./queries";
import { ReasonTip } from "./ReasonTip";

const fmt = (n: number) => n.toLocaleString("en-US");
const label = (a: Asset): string =>
  (a as { name?: string }).name?.replace(/\s*\(synthetic\)/, "") ?? assetName(a.asset_id);

/** One line: the customers this decision protects, with the weighted count of each asset behind the (i). */
export function CeBreakdown({ card }: { card: ProposalCard }) {
  const index = useAssetIndex();
  const weight = POLICIES.policy_ce_weight_hospital.value;
  const rows = card.target_ids
    .map((id) => index.get(id))
    .filter((a): a is Asset => Boolean(a))
    .map((a) => ({
      asset: a,
      facility: a.critical_facility ? weight : 0,
      ce: a.customers_served + (a.critical_facility ? weight : 0),
    }));
  if (card.action_type !== "cross_domain_priority" || rows.length === 0) return null;
  const total = rows.reduce((sum, r) => sum + r.ce, 0);
  return (
    <p
      className="m-0 mb-5 flex items-center gap-1 border-b border-hair pb-3 text-[13px] text-ink-2"
      data-testid="ce-breakdown"
    >
      Customers counted
      <span className="font-semibold text-ink tnum">{fmt(total)}</span>
      <ReasonTip label="How the customers are counted" title="How the customers are counted">
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {rows.map((r) => (
            <li key={r.asset.asset_id}>
              {label(r.asset)}: {fmt(r.asset.customers_served)} served
              {r.facility > 0 && ` plus ${fmt(r.facility)} for a critical facility`}
            </li>
          ))}
        </ul>
      </ReasonTip>
    </p>
  );
}
