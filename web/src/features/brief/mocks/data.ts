import { NUMBERS } from "@/contracts/numbers.gen";
import { freshCards, MOCK_NOW } from "@/mocks/fixtures";
import { type LiveBrief, type LiveSitrep, toBrief } from "../adapt";
import type { Brief, SitrepNumber } from "../types";

const nf = new Intl.NumberFormat("en-US");

/** Customers without power at the mock scenario hour, summed from the replay file `county_hourly.csv`. */
const CUSTOMERS_OUT_NOW = 157_918;
/** Advisory N+1 outage forecast for the footprint: mean, N-advisory mean and p90 sum from `forecast.gen.json`. */
const FORECAST_OUT = { p50: 733_316, low: 431_758, high: 1_333_443 };

export const sitrepNumbers = (): SitrepNumber[] => [
  {
    label: "Customers without power",
    value: nf.format(CUSTOMERS_OUT_NOW),
    source_id: "county_hourly (Helene replay)",
  },
  {
    label: "Footprint counties",
    value: String(NUMBERS.footprint_counties.value),
    source_id: "numbers.yaml footprint_counties",
  },
  { label: "Open decisions needing two signatures", value: "2", source_id: "decision queue" },
  { label: "PS-17 generator hookup decide-by", value: "03:29Z", source_id: "DC-D3-PS17-POWER" },
];

export function sitrepText(asOf: string): string {
  const n = sitrepNumbers();
  return [
    `As of ${asOf.slice(11, 16)}Z on 27 Sep, ${n[0].value} customers are without power across the ${n[1].value} footprint counties.`,
    "Advisory N+2 is the latest. The outage forecast has moved up with each advisory.",
    `${n[2].value} decisions are waiting on two signatures; the first falls due at ${n[3].value} (DC-D3-PS17-POWER).`,
    "PS-17 is on grid power with a full tank. Crews are staged at the Aiken yard.",
  ].join(" ");
}

const slotsOf = (numbers: SitrepNumber[]): Record<string, string> =>
  Object.fromEntries(numbers.map((n, i) => [`E${i + 1}.${n.label}`, n.value]));

export const makeSitrep = (runId: string, promoted: boolean): LiveSitrep => ({
  run_id: runId,
  thread_id: "thr-mock-sitrep",
  drafted_by: "ops_dm_01",
  started_at: MOCK_NOW,
  as_of_utc: MOCK_NOW,
  tier: "T1",
  path: "llm",
  text: sitrepText(MOCK_NOW),
  slots: slotsOf(sitrepNumbers()),
  tainted: false,
  status: promoted ? "promoted" : "draft",
  promoted_by: promoted ? "ic_01" : null,
  promoted_at: promoted ? MOCK_NOW : null,
  audit_seq: promoted ? 4600 : null,
  classification: "C2",
});

export const earlierSitrep = (): LiveSitrep => ({
  run_id: "run-sitrep-0921",
  thread_id: "thr-mock-sitrep-0921",
  drafted_by: "ops_dm_01",
  started_at: "2024-09-26T21:08:00Z",
  as_of_utc: "2024-09-26T21:00:00Z",
  tier: "T1",
  path: "llm",
  text: "As of 21:00Z on 26 Sep, no customers in the footprint are without power beyond the usual baseline. Advisory N+2 was issued. Crews are staging at the Aiken yard and PS-17 is on grid power.",
  slots: { "E1.advisory": "N+2", "E2.crews_staging": "Aiken yard" },
  tainted: false,
  status: "promoted",
  promoted_by: "ic_01",
  promoted_at: "2024-09-26T21:15:00Z",
  audit_seq: 4521,
  classification: "C2",
});

const provenance = (source: string, asOf: string | null = MOCK_NOW) => ({
  source,
  model_id: null,
  rule_id: null,
  as_of: asOf,
  label: "S" as const,
  detail: null,
});

export function initialLiveBrief(): LiveBrief {
  const t3 = freshCards().filter((c) => c.tier === "T3");
  return {
    as_of: MOCK_NOW,
    status_word: "Warning",
    status_basis: "an open T3 decision is due in under 60 minutes",
    numbers: [
      {
        key: "customers_out",
        label: "Customers out",
        actual: CUSTOMERS_OUT_NOW,
        forecast: FORECAST_OUT.p50,
        forecast_basis: "sum of county median peaks, advisory N+2",
        unit: "customers",
        breakdown: {},
        provenance: provenance("Outage reports by county; outage forecast"),
      },
      {
        key: "critical_facilities",
        label: "Critical facilities affected",
        actual: 1,
        forecast: null,
        forecast_basis: null,
        unit: "facilities",
        breakdown: {},
        provenance: provenance("Outage reports (open outages)"),
      },
      {
        key: "water_zones_advisory",
        label: "Water zones under advisory",
        actual: 0,
        forecast: 1,
        forecast_basis: "zones at or above the policy line, or with an advisory due, proposed or issued",
        unit: "zones",
        breakdown: {},
        provenance: provenance("Water advisory register", null),
      },
      {
        key: "crews_working",
        label: "Crews working",
        actual: 5,
        forecast: null,
        forecast_basis: null,
        unit: "crews",
        breakdown: {},
        provenance: provenance("Crew tracking (latest status per crew)"),
      },
    ],
    open_t3: t3,
    functions: [
      {
        function: "command",
        sentence: "Two decisions need two signatures; the first falls due at 23:29 ET (03:29Z).",
      },
      {
        function: "operations",
        sentence: "Feeder FDR-AIK-2207 is the restoration priority because it supplies PS-17.",
      },
      {
        function: "water_operations",
        sentence: "0 water zones under a boil-water advisory; 1 expected to need one.",
      },
      { function: "logistics", sentence: "5 crews working, 9 staged, 4 available." },
    ],
    last_advisory: {
      label: "N+2",
      issued_utc: "2024-09-26T21:00:00Z",
      landfall_eta_utc: "2024-09-27T03:10:00Z",
      next_advisory_utc: "2024-09-27T03:00:00Z",
    },
    caveat:
      "Forecasts are estimates, not promises. The model has under-called large storms: for Helene it gave 0.36 M customers out against 2.31 M. The 80% range comes from synthetic test storms.",
    label: "S",
  };
}

export const initialSitreps = (): LiveSitrep[] => [earlierSitrep()];

export const initialBrief = (): Brief => toBrief(initialLiveBrief(), initialSitreps());
