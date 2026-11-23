import { HttpResponse, http } from "msw";
import forecastData from "./mock/forecast.gen.json";
import v1 from "./mock/outage_loso.json";
import v2 from "./mock/outage_loso_v2.json";
import whatIfData from "./mock/whatif.gen.json";

const notFound = (what: string) =>
  HttpResponse.json({ error: { code: "NOT_FOUND", message: `unknown ${what}` } }, { status: 404 });

const reports: Record<string, unknown> = { outage_loso: v1, outage_loso_v2: v2 };

export const handlers = [
  http.get("/api/forecasts/outages/counties", ({ request }) => {
    const label = new URL(request.url).searchParams.get("advisory") ?? "";
    const found = (forecastData.advisories as Record<string, unknown>)[label];
    return found ? HttpResponse.json(found as Record<string, unknown>) : notFound("advisory");
  }),
  http.get("/api/forecasts/outages/plan-diff", ({ request }) => {
    const label = new URL(request.url).searchParams.get("to") ?? "";
    const found = (forecastData.plan_diffs as Record<string, unknown>)[label];
    return found
      ? HttpResponse.json(found as Record<string, unknown>)
      : HttpResponse.json(
          { error: { code: "PLAN_DIFF_NOT_PUBLISHED", message: `no plan diff ${label} published` } },
          { status: 404 },
        );
  }),
  http.get("/api/whatif", () => HttpResponse.json(whatIfData)),
  http.get("/api/models/:name/evaluation", ({ params }) => {
    const found = reports[String(params.name)];
    return found ? HttpResponse.json(found as Record<string, unknown>) : undefined;
  }),
];
