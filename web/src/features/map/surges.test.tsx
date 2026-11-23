import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SurgeLine } from "@/features/brief/SurgeLine";
import { server } from "@/mocks/server";
import type { FeatureCollection } from "./geo";
import counties from "./geo/counties.geo.json";
import { DEFAULT_LAYERS } from "./layers";
import surgeData from "./mock/surges.gen.json";
import { type OutageSurge, surgeCollection, surgeLabels, surgeStarts, surgeTip } from "./surges";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
afterEach(() => server.resetHandlers());

const late = surgeData.reports[surgeData.reports.length - 1] as { as_of: string; surges: OutageSurge[] };
const surges = late.surges;
const fc = counties as unknown as FeatureCollection;

describe("outage surge layer", () => {
  it("is off by default", () => {
    expect(DEFAULT_LAYERS.surges).toBe(false);
  });

  it("covers exactly the surging counties and labels each with its start time", () => {
    const outlines = surgeCollection(fc, surges, late.as_of);
    expect(outlines.features.map((f) => String(f.properties.fips)).sort()).toEqual(
      surges.map((s) => s.fips).sort(),
    );
    const labels = surgeLabels(fc, surges);
    expect(labels).toHaveLength(surges.length);
    expect(labels[0]?.text).toMatch(/^from [A-Z][a-z]{2} \d{1,2} \d{2}:\d{2} ET$/);
  });

  it("colours by start time and outlines only the counties whose surge began in the last 3 hours", () => {
    const at = (iso: string, fips: string): OutageSurge => ({
      ...(surges[0] as OutageSurge),
      fips,
      onset_at: iso,
    });
    const list = [
      at("2024-09-26T13:15:00Z", "13033"),
      at("2024-09-26T13:15:00Z", "13245"),
      at("2024-09-27T00:00:00Z", "13189"),
    ];
    const asOf = "2024-09-27T01:00:00Z";
    const props = surgeCollection(fc, list, asOf).features.map((f) => [
      f.properties.onset,
      f.properties.recent,
    ]);
    expect(props).toContainEqual([Date.parse("2024-09-26T13:15:00Z"), false]);
    expect(props).toContainEqual([Date.parse("2024-09-27T00:00:00Z"), true]);
    expect(surgeStarts(list, asOf)).toEqual({
      first: "2024-09-26T13:15:00Z",
      last: "2024-09-27T00:00:00Z",
      recent: 1,
    });
    expect(surgeStarts([], asOf)).toBeNull();
  });

  it("says where, since when, how many are out and how sure the detector is", () => {
    const s = surges[0] as OutageSurge;
    const tip = surgeTip(s);
    expect(tip.text).toBe(`Outage surge in ${s.county}, ${s.state}`);
    expect(tip.detail).toMatch(
      /^Since .+, [\d,]+ customers out \((under 1%|\d+%) of the county\), (high|medium|low) confidence$/,
    );
  });
});

function show(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>{ui}</TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("briefing surge number", () => {
  it("shows the count of counties with an active surge at the briefing time", async () => {
    show(<SurgeLine asOf="2024-09-27T01:00:00Z" />);
    expect((await screen.findByTestId("surge-count")).textContent).toBe(String(surges.length));
  });

  it("says the read failed instead of showing zero", async () => {
    server.use(
      http.get("/api/outages/surges", () =>
        HttpResponse.json({ error: { code: "SURGES_UNAVAILABLE", message: "no baseline" } }, { status: 404 }),
      ),
    );
    show(<SurgeLine asOf="2024-09-27T01:00:00Z" />);
    expect((await screen.findByTestId("surge-line")).textContent).toContain("aren't available");
    expect(screen.queryByTestId("surge-count")).toBeNull();
  });
});
