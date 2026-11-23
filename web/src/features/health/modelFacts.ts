import { humanize } from "./format";
import type { EvalRow, ModelEvaluation } from "./types";

export type FactFormat = "percent" | "percent1" | "ratio" | "of_n" | "yesno" | "plain";

export interface FactSpec {
  label: string;
  /** Matches the end of the K17 metric name. */
  metric: string;
  format: FactFormat;
  /** Show the met / below-target mark from the report's own `passed` flag. */
  mark?: boolean;
  unit?: string;
  /** Plain words for what the target means; `{t}` is the report's own threshold. */
  targetLabel?: string;
}

export interface ModelSpec {
  match: RegExp;
  title: string;
  does: string;
  /** Plain statements that frame the numbers; they carry no figures of their own. */
  wording?: string[];
  facts?: FactSpec[];
}

const UNBIASED = "a forecast with no bias would read {t}";

export const MODEL_SPECS: ModelSpec[] = [
  {
    match: /^(outage|a2)/i,
    title: "Outage forecast",
    does: "Forecasts customers without power by county during a storm, with a range.",
    wording: [
      "The forecast is the fitted wind-fragility curve, shown with its range. Machine-learning variants were tested against it in a test fixed in advance and did not beat it.",
      "The curve under-calls large storms, most of all inland ones like Helene, so crews are never sized on the forecast alone.",
    ],
    facts: [
      {
        label: "Storms where the total was forecast too low",
        metric: "S5.storms_under_predicted_total",
        format: "of_n",
        mark: true,
      },
      {
        label: "Outages forecast, as a share of those observed",
        metric: "S5.pooled_forecast_over_observed",
        format: "percent",
        mark: true,
        targetLabel: UNBIASED,
      },
      {
        label: "The same, for the eight largest storms",
        metric: "S5.pooled_forecast_over_observed_large8",
        format: "percent",
        mark: true,
        targetLabel: UNBIASED,
      },
      {
        label: "County error of the machine-learning model, against the curve",
        metric: "M1.median_county_mae_ratio_vs_b3",
        format: "ratio",
      },
      { label: "Needed to replace the curve", metric: "ml_bar_M1_passed", format: "yesno" },
    ],
  },
  {
    match: /anomaly/i,
    title: "Water fault detector",
    does: "Flags pressure and tank-level faults at pump stations from SCADA readings.",
    wording: ["It finds fewer faults than its target, and slow leaks are the ones it misses most."],
    facts: [
      { label: "Test faults caught", metric: "anomaly.recall_raw", format: "percent", mark: true },
      { label: "Slow leaks found", metric: "anomaly.recall.leak", format: "percent", mark: true },
      {
        label: "False alarms per 100 station-days",
        metric: "anomaly.false_alarms_per_100_asset_days",
        format: "plain",
        mark: true,
      },
    ],
  },
  {
    match: /etr/i,
    title: "Restoration time estimate",
    does: "Estimates when each county is 50% and 90% restored.",
    facts: [
      {
        label: "Error in time to 90% restored (counties not in training)",
        metric: "county_t90_p75_rel_error_not_fitted",
        format: "percent1",
        mark: true,
      },
      {
        label: "Error in time to 50% restored (counties not in training)",
        metric: "county_t50_p75_rel_error_not_fitted",
        format: "percent1",
        mark: true,
      },
      {
        label: "Counties off by more than a week",
        metric: "county_t90_share_over_week_abs_error_not_fitted",
        format: "percent1",
        mark: true,
      },
    ],
  },
  {
    match: /saa/i,
    title: "Crew planner",
    does: "Chooses where to stage crews so the plan holds up across storm scenarios.",
    facts: [
      {
        label: "Saved by planning for the full range",
        metric: "saa.coa_a.vss_vs_ev_out_of_sample",
        format: "plain",
        unit: "customer-hours",
      },
      {
        label: "Most a perfect forecast could save",
        metric: "saa.coa_a.evpi_out_of_sample",
        format: "plain",
        unit: "customer-hours",
      },
      {
        label: "Longest planning time",
        metric: "saa.coa_a.solve_seconds_max_over_replications",
        format: "plain",
        unit: "s",
      },
    ],
  },
  {
    match: /ladi/i,
    title: "Damage from photos",
    does: "Spots pole and line damage in storm photos. Tested on a small public photo set, not on SGW photos.",
    facts: [
      { label: "Score on test photos (mAP)", metric: "test_map", format: "plain", unit: "%", mark: true },
      {
        label: "Score on tuning photos (mAP)",
        metric: "validation_map",
        format: "plain",
        unit: "%",
        mark: true,
      },
    ],
  },
];

export const specFor = (name: string): ModelSpec | undefined => MODEL_SPECS.find((s) => s.match.test(name));

export const reportRows = (ev: ModelEvaluation | undefined): EvalRow[] =>
  ev?.eval_report?.metrics ?? ev?.metrics ?? [];

export const reportDate = (ev: ModelEvaluation | undefined): string | null =>
  ev?.eval_report?.created_at ?? ev?.created_at ?? null;

export const reportName = (ev: ModelEvaluation | undefined): string | null =>
  ev?.eval_report?.name ?? ev?.name ?? null;

export function formatValue(value: number, format: FactFormat, row: EvalRow, unit?: string): string {
  switch (format) {
    case "percent":
      return `${Math.round(value * 100)}%`;
    case "percent1":
      return `${(value * 100).toFixed(1)}%`;
    case "ratio":
      return `${value.toFixed(2)}×`;
    case "of_n":
      return `${Math.round(value)} of ${row.n}`;
    case "yesno":
      return value >= 1 ? "Met" : "Below target";
    default: {
      const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
      const text = value.toLocaleString("en-US", { maximumFractionDigits: digits });
      return unit === "%" ? `${text}%` : `${text}${unit ? ` ${unit}` : ""}`;
    }
  }
}

export interface Fact {
  label: string;
  value: string;
  /** "met" or "below" from the report's own pass flag; null when the fact carries no mark. */
  mark: "met" | "below" | null;
  target: string | null;
}

function targetText(row: EvalRow, spec: FactSpec): string | null {
  if (row.threshold === null || spec.format === "yesno" || spec.format === "of_n") return null;
  const t = formatValue(row.threshold, spec.format, row, spec.unit);
  if (spec.targetLabel) return spec.targetLabel.replace("{t}", t);
  return `target ${row.direction === "higher_is_better" ? "at least" : "at most"} ${t}`;
}

function generic(rows: EvalRow[]): Fact[] {
  const pool = rows.filter((r) => r.passed !== null && !/in_sample/.test(r.metric));
  const picked = (pool.length ? pool : rows).slice(0, 3);
  return picked.map((r) => ({
    label: humanize(r.metric.split(".").slice(-1)[0] ?? r.metric),
    value: formatValue(r.value, "plain", r, r.unit.length <= 14 ? r.unit : undefined),
    mark: r.passed === null ? null : r.passed ? "met" : "below",
    target: null,
  }));
}

export function factsFor(spec: ModelSpec | undefined, rows: EvalRow[]): Fact[] {
  if (!spec?.facts) return generic(rows);
  return spec.facts.flatMap((f) => {
    const row = rows.find((r) => r.metric.endsWith(f.metric));
    if (!row) return [];
    return [
      {
        label: f.label,
        value: formatValue(row.value, f.format, row, f.unit),
        mark: f.mark && row.passed !== null ? (row.passed ? "met" : "below") : null,
        target: f.mark ? targetText(row, f) : null,
      },
    ];
  });
}
