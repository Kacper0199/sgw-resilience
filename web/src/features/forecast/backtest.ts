import type { K17Report, K17Row } from "./types";

const PER_STORM = new Set([
  "county_mae",
  "spearman",
  "coverage_80",
  "coverage_95",
  "rel_total_error",
  "worst_miss",
  "county_mae_vs_fragility_fitted",
  "rel_total_error_vs_fragility_fitted",
  "rel_total_error_vs_fragility_prior",
]);

export interface Compared {
  model: number;
  wind: number | null;
  curve: number | null;
}

export interface StormResult {
  key: string;
  name: string;
  county: Compared | null;
  total: Compared | null;
  coverage80: { value: number; nominal: number | null; passed: boolean | null } | null;
  worstMiss: Compared | null;
}

export interface SummaryRow {
  metric: string;
  label: string;
  value: number;
  unit: string;
  baseline: string | null;
  baselineValue: number | null;
  passed: boolean | null;
}

export interface Backtest {
  storms: StormResult[];
  summary: SummaryRow[];
  countyCurve: boolean;
  totalCurve: boolean;
  windName: string | null;
  curveName: string | null;
  basis: string;
  coverageMisses: { storm: string; value: number; nominal: number | null }[];
}

const SUMMARY_LABEL: Record<string, string> = {
  storms_model_beats_baseline_rel_total_error: "Storms where the total beat the wind rule",
  storms_s2_beats_wind_threshold_county_mae: "Storms with lower county error than the wind rule",
  storms_s2_beats_fragility_fitted_county_mae: "Storms with lower county error than the fitted damage curve",
  storms_s2_same_as_fragility_fitted_county_mae: "Storms where the forecast equals the fitted curve",
  storms_s2_worse_as_fragility_fitted_county_mae:
    "Storms with higher county error than the fitted damage curve",
  storms_s2_under_predicted_total: "Storms where the forecast total fell below what happened",
  s2_share_of_observed_outages_forecast: "Share of all outages the forecast caught",
  s2_median_county_mae_ratio_vs_wind_threshold: "Median county error, relative to the wind rule",
  s2_median_spearman: "County ranking score (median)",
  storms_s2_spearman_better_than_wind_threshold: "Storms where the county ranking beat the wind rule",
  s2_vs_fragility_fitted_wilcoxon_p: "Could it be chance? (p-value)",
};

export function titleCase(key: string): string {
  const spaced = key.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const BASELINE_LABEL: [RegExp, string][] = [
  [/^wind_threshold/, "Wind rule"],
  [/^fragility_prior/, "Standard damage curve"],
  [/^fragility_fitted/, "Damage curve fitted to past storms"],
];

export function baselineLabel(name: string | null): string | null {
  if (!name) return null;
  return BASELINE_LABEL.find(([re]) => re.test(name))?.[1] ?? titleCase(name.split(" (")[0] ?? name);
}

const summaryLabel = (metric: string) => SUMMARY_LABEL[metric] ?? titleCase(metric);

function segments(row: K17Row, report: K17Report): string[] {
  const rest = row.metric.startsWith(`${report.name}.`)
    ? row.metric.slice(report.name.length + 1)
    : row.metric;
  return rest.split(".");
}

/** Reads a K17 report into per-storm rows and summary rows. It works on the 4-storm and the 24-storm report alike. */
export function parseBacktest(report: K17Report): Backtest {
  const stormRows = new Map<string, Map<string, K17Row>>();
  const summary: SummaryRow[] = [];
  let basis = "";
  for (const row of report.metrics) {
    const seg = segments(row, report);
    const last = seg[seg.length - 1] as string;
    if (seg.length === 3 && PER_STORM.has(last)) {
      const storm = seg[1] as string;
      basis = seg[0] as string;
      if (!stormRows.has(storm)) stormRows.set(storm, new Map());
      stormRows.get(storm)?.set(last, row);
    } else if (seg.length === 2) {
      summary.push({
        metric: last,
        label: summaryLabel(last),
        value: row.value,
        unit: row.unit,
        baseline: row.baseline_name,
        baselineValue: row.baseline_value,
        passed: row.passed,
      });
    }
  }
  const curveKey = (m: Map<string, K17Row>, kinds: string[]) => kinds.map((k) => m.get(k)).find(Boolean);
  const storms: StormResult[] = [...stormRows].map(([key, m]) => {
    const county = m.get("county_mae");
    const countyCurve = m.get("county_mae_vs_fragility_fitted");
    const total = m.get("rel_total_error");
    const totalCurve = curveKey(m, [
      "rel_total_error_vs_fragility_fitted",
      "rel_total_error_vs_fragility_prior",
    ]);
    const cov = m.get("coverage_80");
    const worst = m.get("worst_miss");
    return {
      key,
      name: titleCase(key.replace(/_(\d{4})$/, " $1")),
      county: county
        ? { model: county.value, wind: county.baseline_value, curve: countyCurve?.baseline_value ?? null }
        : null,
      total: total
        ? { model: total.value, wind: total.baseline_value, curve: totalCurve?.baseline_value ?? null }
        : null,
      coverage80: cov ? { value: cov.value, nominal: cov.baseline_value, passed: cov.passed } : null,
      worstMiss: worst ? { model: worst.value, wind: worst.baseline_value, curve: null } : null,
    };
  });
  const first = [...stormRows.values()][0];
  const windName = baselineLabel(first?.get("county_mae")?.baseline_name ?? null);
  const curveRow =
    first &&
    curveKey(first, [
      "county_mae_vs_fragility_fitted",
      "rel_total_error_vs_fragility_fitted",
      "rel_total_error_vs_fragility_prior",
    ]);
  return {
    storms,
    summary,
    countyCurve: storms.some((s) => s.county?.curve != null),
    totalCurve: storms.some((s) => s.total?.curve != null),
    windName,
    curveName: baselineLabel(curveRow?.baseline_name ?? null),
    basis,
    coverageMisses: storms.flatMap((s) =>
      s.coverage80 && s.coverage80.passed === false
        ? [{ storm: s.name, value: s.coverage80.value, nominal: s.coverage80.nominal }]
        : [],
    ),
  };
}

export const BASIS_LABEL: Record<string, string> = {
  hindcast_observed_track: "Rerun on the real storm tracks",
};
