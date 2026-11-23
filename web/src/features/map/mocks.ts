import { HttpResponse, http } from "msw";
import { waterAssets } from "../water/mocks";
import assetData from "./mock/assets.gen.json";
import countyOutages from "./mock/county-outages.gen.json";
import hazardData from "./mock/hazard.gen.json";
import observedData from "./mock/observed.gen.json";
import riskData from "./mock/risk.gen.json";
import surgeData from "./mock/surges.gen.json";

const advisories = hazardData.advisories;
const risk = riskData as Record<string, { as_of: string; snapshot_id: string; items: unknown[] }>;

const notFound = (what: string) =>
  HttpResponse.json({ error: { code: "NOT_FOUND", message: `unknown ${what}` } }, { status: 404 });

function advisoryFor(asOf: string | null) {
  const at = asOf ? Date.parse(asOf) : Number.NaN;
  const issued = advisories.filter((a) => Date.parse(a.issued_utc) <= at);
  return issued[issued.length - 1] ?? advisories[0];
}

export const handlers = [
  http.get("/api/regions", () => HttpResponse.json(assetData.regions)),
  http.get("/api/assets", ({ request }) => {
    const domain = new URL(request.url).searchParams.get("domain");
    const known = new Set(assetData.assets.map((a) => a.asset_id));
    const all = [...assetData.assets, ...waterAssets.filter((a) => !known.has(a.asset_id))];
    return HttpResponse.json(domain ? all.filter((a) => a.domain === domain) : all);
  }),
  http.get("/api/risk", ({ request }) => {
    const adv = advisoryFor(new URL(request.url).searchParams.get("as_of"));
    return HttpResponse.json(risk[adv?.advisory_label ?? ""] ?? null);
  }),
  http.get("/api/hazard/advisories", () =>
    HttpResponse.json(
      advisories.map(({ advisory_label, issued_utc, next_advisory_utc }) => ({
        advisory_label,
        issued_utc,
        next_advisory_utc,
      })),
    ),
  ),
  http.get("/api/hazard/advisories/:label", ({ params }) => {
    const adv = advisories.find((a) => a.advisory_label === params.label);
    return adv ? HttpResponse.json({ ...adv, cone: hazardData.cone }) : notFound("advisory");
  }),
];

const snapshots = observedData.observed;

/** The latest exported snapshot at or before `as_of` (the first one before any). */
function observedFor(asOf: string | null) {
  const at = asOf ? Date.parse(asOf) : Number.POSITIVE_INFINITY;
  const earlier = snapshots.filter((s) => Date.parse(s.as_of) <= at);
  return earlier[earlier.length - 1] ?? snapshots[0];
}

handlers.push(
  http.get("/api/hazard/observed", ({ request }) =>
    HttpResponse.json(observedFor(new URL(request.url).searchParams.get("as_of"))),
  ),
  http.get("/api/after-action/official-record", () => HttpResponse.json(observedData.record)),
  http.get("/api/outages/surges", ({ request }) => {
    const asOf = new URL(request.url).searchParams.get("as_of");
    const at = asOf ? Date.parse(asOf) : Number.POSITIVE_INFINITY;
    const earlier = surgeData.reports.filter((r) => Date.parse(r.as_of) <= at);
    const report = earlier[earlier.length - 1] ?? surgeData.reports[0];
    return HttpResponse.json({ ...report, as_of: asOf ?? report?.as_of });
  }),
  http.get("/api/outages/counties", ({ request }) => {
    const asOf = new URL(request.url).searchParams.get("as_of");
    const at = asOf ? Date.parse(asOf) : Number.POSITIVE_INFINITY;
    const earlier = countyOutages.reports.filter((r) => Date.parse(r.as_of) <= at);
    return HttpResponse.json(
      earlier[earlier.length - 1] ?? { as_of: null, customers_out_now: 0, counties: [] },
    );
  }),
);
