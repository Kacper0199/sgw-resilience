import { ClipboardList } from "lucide-react";
import type * as React from "react";
import { InfoTip, LoadingState } from "@/components/sgw";
import type { GlossaryKey } from "@/content/glossary";
import { ReasonTip } from "@/features/decisions/ReasonTip";
import { LoadFailed } from "@/features/water/LoadFailed";
import { cn } from "@/lib/cn";
import { deltaPercent, int, millions, PLAN_UI, usdMillions } from "./format";
import type { CrewPlan, CrewPlanDocument, PlanId } from "./types";
import { useCrewPlan } from "./useCrews";

interface Row {
  key: string;
  label: string;
  info?: GlossaryKey;
  cell: (p: CrewPlan, base: CrewPlan) => React.ReactNode;
  emphasis?: boolean;
}

const ORDER: PlanId[] = ["P50", "COA-A", "COA-B", "COA-C"];

const delta = (p: CrewPlan, now: number, base: number) =>
  p.plan_id === "P50" ? null : (
    <span className="ml-1.5 text-[12px] font-normal text-muted">{deltaPercent(now, base)}</span>
  );

const ROWS: Row[] = [
  {
    key: "early",
    label: "Early mutual aid (crews)",
    info: "mutual_aid",
    cell: (p) => `${int(p.early_mutual_aid_groups)} crews`,
  },
  {
    key: "aid",
    label: "Mutual-aid cost",
    cell: (p) => usdMillions(p.expected_cost.total_mutual_aid_usd),
  },
  {
    key: "expected",
    label: "Expected delay (customer-hours)",
    info: "customer_hours",
    emphasis: true,
    cell: (p, base) => (
      <>
        {millions(p.out_of_sample.expected_customer_hours)}
        {delta(p, p.out_of_sample.expected_customer_hours, base.out_of_sample.expected_customer_hours)}
      </>
    ),
  },
  {
    key: "bad",
    label: "Bad-storm delay (customer-hours)",
    info: "bad_storm",
    cell: (p, base) => (
      <>
        {millions(p.out_of_sample.p90_customer_hours)}
        {delta(p, p.out_of_sample.p90_customer_hours, base.out_of_sample.p90_customer_hours)}
      </>
    ),
  },
  {
    key: "idle",
    label: "Idle if the storm is small (people)",
    info: "idle_crews",
    cell: (p) => int(p.out_of_sample.expected_idle_early_mutual_aid_persons),
  },
];

function AboutPlans({ doc }: { doc: CrewPlanDocument }) {
  const { vss, evpi, planning_band_check: band, forecast_scale_band: k } = doc;
  return (
    <ReasonTip label="About these numbers" title="About these numbers">
      <p className="m-0" data-testid="plan-facts">
        Planning for the full range saves {int(vss.p50.value)} customer-hours against the standard plan (95%
        range {int(vss.p50.ci_low)} to {int(vss.p50.ci_high)}). A perfect forecast could save at most{" "}
        {int(evpi.out_of_sample)}, tested on {int(evpi.out_of_sample_n)} new storms.
      </p>
      <p className="m-0" data-testid="plan-caveat">
        In the Helene replay the real need is {band.synthetic_truth_requirement_over_p50.toFixed(1)} times the
        median forecast
        {band.inside_planning_band
          ? ""
          : `, outside the ${k.k_low.toFixed(2)} to ${k.k_high.toFixed(2)} times the plans were built for`}
        . Aid that arrives after landfall fills the gap.
      </p>
      <p className="m-0" data-testid="plan-limits">
        Each option may move ±{envelopePct(doc)}% per yard without new signatures; yards with fewer than 5
        crews are locked. Site limit {int(doc.staging_rules.site_cap_persons)} people.
      </p>
      <p className="m-0">
        Based on {doc.size.scenarios} planning scenarios and {int(doc.size.out_of_sample)} test storms. The
        platform doesn't pick an option; the two approvers do.
      </p>
    </ReasonTip>
  );
}

const envelopePct = (doc: CrewPlanDocument): number => doc.plans.find((p) => p.envelope)?.envelope?.pct ?? 0;

/** Four plans side by side, none preselected: what each saves and what it leaves open. */
export function PlanOptions() {
  const q = useCrewPlan();
  const doc = q.data;
  const base = doc?.plans.find((p) => p.plan_id === "P50");
  const plans = [...(doc?.plans ?? [])].sort((a, b) => ORDER.indexOf(a.plan_id) - ORDER.indexOf(b.plan_id));
  if (q.error)
    return (
      <LoadFailed
        thing="the crew plan"
        icon={ClipboardList}
        error={q.error}
        onRetry={() => void q.refetch()}
      />
    );
  if (q.isPending || !doc || !base) return <LoadingState label="Loading crew plan…" rows={4} />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] border-collapse text-[13px]" data-testid="plan-table">
        <caption className="sr-only">Crew plans compared with the standard plan</caption>
        <thead>
          <tr>
            <th
              scope="col"
              className="w-[210px] border-b border-hair-strong py-2 pr-3 pl-8 text-left align-top text-[12px] font-semibold text-muted"
            >
              <span className="inline-flex items-center gap-1">
                Average per storm
                <AboutPlans doc={doc} />
              </span>
            </th>
            {plans.map((p) => {
              const ui = PLAN_UI[p.plan_id];
              const isBase = p.plan_id === "P50";
              return (
                <th
                  key={p.plan_id}
                  scope="col"
                  className="border-b border-hair-strong px-3 py-2 text-left align-top last:pr-8"
                >
                  <span className="inline-flex items-center gap-1 text-[14px] font-semibold">
                    {ui.name}
                    {isBase && <InfoTip term="p50" />}
                  </span>
                  <span className="mt-0.5 block text-[12px] font-normal text-muted">{ui.blurb}</span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => (
            <tr key={r.key} className="border-b border-hair" data-testid={`plan-row-${r.key}`}>
              <th scope="row" className="py-2.5 pr-3 pl-8 text-left align-top text-[13px] font-semibold">
                <span className="inline-flex items-center gap-1">
                  {r.label}
                  {r.info && <InfoTip term={r.info} />}
                </span>
              </th>
              {plans.map((p) => (
                <td
                  key={p.plan_id}
                  className={cn(
                    "px-3 py-2.5 align-top tnum last:pr-8",
                    r.emphasis ? "text-[16px] font-semibold" : "text-[14px] font-medium",
                  )}
                >
                  {r.cell(p, base)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
