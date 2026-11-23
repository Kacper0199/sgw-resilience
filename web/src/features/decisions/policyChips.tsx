import { Link } from "react-router";
import { cn } from "@/lib/cn";
import { usePolicies } from "./queries";

const NAME: Record<string, string> = {
  policy_envelope_pct: "Pre-approved limits",
  policy_break_glass_cosign_hours: "Co-sign window",
  policy_ce_weight_hospital: "Hospital weight",
  policy_equity_weight: "Equity weight",
  policy_no_regret_act_now_ppm: "Act-now level",
  policy_approval_ttl_t3_min: "T3 signatures expire after",
  policy_evidence_age_t3_min: "T3 evidence max age",
};

const unitText = (unit: string, value: number | string) => {
  if (unit === "ppm of scenarios" && typeof value === "number")
    return `${Math.round(value / 10_000)}% of scenarios`;
  if (unit === "percent") return `${value}%`;
  if (unit === "hours") return `${value} h`;
  if (unit === "minutes") return `${value} min`;
  return `${value} ${unit}`;
};

/** The policy values a decision rests on as quiet text rows, not boxes; each links to Admin → Policies. */
export function PolicyChips({ keys, className }: { keys: string[]; className?: string }) {
  const params = usePolicies().data;
  const shown = (params ?? []).filter((p) => keys.includes(p.key));
  if (shown.length === 0) return null;
  return (
    <ul
      className={cn("m-0 mt-1 mb-6 flex list-none flex-col gap-1 p-0 text-[12px] leading-[1.6]", className)}
      aria-label="Policy values"
      data-testid="policy-chips"
    >
      {shown.map((p) => (
        <li key={p.key} className="flex flex-wrap items-baseline gap-x-2">
          <Link
            to={`/admin?tab=policies&key=${encodeURIComponent(p.key)}`}
            className={cn(
              "inline-flex items-baseline gap-1.5 text-ink no-underline hover:text-blue-ink hover:underline",
            )}
          >
            <span className="font-medium">{NAME[p.key] ?? p.key}</span>
            <span className="tnum">{unitText(p.unit, p.value)}</span>
          </Link>
          <span className="text-muted">{p.chip}</span>
        </li>
      ))}
    </ul>
  );
}
