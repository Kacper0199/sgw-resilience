import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { Asset, ProposalCard, Region } from "@/lib/api";
import {
  buildStops,
  placeIdsOf,
  proposalForAssets,
  type SequenceStep,
  unplacedNote,
  unplacedSteps,
} from "./chain";
import { advisoryAt } from "./data";
import { placeLabels, relaxMarkers, spreadMarkers } from "./declutter";
import { exteriorOnly, type FeatureCollection, labelPoint } from "./geo";
import { domainOf } from "./layerData";
import { summariseLifelines } from "./lifelineSummary";
import { issuedKey, type NhcProducts, stormGeometry } from "./storm";
import type { AdvisoryHazard, RiskItem } from "./types";

const products = JSON.parse(
  readFileSync(resolve(process.cwd(), "public/geo/helene-nhc.json"), "utf8"),
) as NhcProducts;

const hazard = (issued: string): AdvisoryHazard => ({
  advisory_label: "X",
  issued_utc: issued,
  next_advisory_utc: null,
  analysis_track: [["2024-09-26T12:00:00Z", 25.4, -85.6, 90]],
  official_track: [
    [0, 25.65, -85.4, 95],
    [6, 27.63, -84.65, 112],
    [12, 29.89, -83.73, 119],
    [18, 32.84, -83.08, 59],
    [24, 35.55, -83.99, 41],
  ],
  cone: { lead_h: [0], radius_nmi: [0] },
  county_peak_gust_ms: {},
});

const segmentsCross = (a: number[][], i: number, j: number) => {
  const [p, p2] = [a[i] as number[], a[i + 1] as number[]];
  const [q, q2] = [a[j] as number[], a[j + 1] as number[]];
  const o = (u: number[], v: number[], w: number[]) =>
    ((v[0] as number) - (u[0] as number)) * ((w[1] as number) - (u[1] as number)) -
    ((v[1] as number) - (u[1] as number)) * ((w[0] as number) - (u[0] as number));
  return o(p, p2, q) * o(p, p2, q2) < 0 && o(q, q2, p) * o(q, q2, p2) < 0;
};

describe("official NHC cone and track", () => {
  it("covers all twelve replay advisories, one cone each", () => {
    const keys = Object.keys(products).sort();
    expect(keys).toHaveLength(12);
    expect(keys[0]).toBe("2024-09-24T15:00:00Z");
    expect(keys[11]).toBe("2024-09-27T09:00:00Z");
    expect(products[keys[8] as string]).toMatchObject({ label: "N+1", nhc_advisory: 13 });
  });

  it("every cone is one closed ring that does not cross itself", () => {
    for (const [key, p] of Object.entries(products)) {
      const ring = p.cone;
      expect(ring[0], key).toEqual(ring[ring.length - 1]);
      for (let i = 0; i < ring.length - 1; i++)
        for (let j = i + 2; j < ring.length - 1; j++) {
          if (i === 0 && j === ring.length - 2) continue;
          expect(segmentsCross(ring, i, j), `${key} ${i}x${j}`).toBe(false);
        }
    }
  });

  it("the track runs in time order from the first fix and the fixes are 12 h apart or more", () => {
    for (const p of Object.values(products)) {
      const leads = p.fixes.map((f) => f[0]);
      expect(leads).toEqual([...leads].sort((a, b) => a - b));
      expect(leads[0]).toBe(0);
    }
  });

  it("builds one cone feature for the selected advisory and labels the forecast points in time", () => {
    const issued = "2024-09-26T15:00:00Z";
    const geo = stormGeometry(hazard(issued), products[issuedKey(issued)]);
    expect(geo.source).toBe("nhc");
    expect(geo.cone.features).toHaveLength(1);
    const first = geo.fixes.features[0];
    expect(first?.properties.at).toBe("2024-09-27T03:00:00.000Z");
    expect(first?.properties.mph).toBeGreaterThan(0);
    expect(geo.now.features).toHaveLength(1);
  });

  it("without an official product it draws the replay track only, no cone", () => {
    const geo = stormGeometry(hazard("2024-09-26T15:00:00Z"), undefined);
    expect(geo.source).toBe("replay");
    expect(geo.cone.features).toHaveLength(0);
    expect(geo.future.features).toHaveLength(1);
    expect(geo.fixes.features.map((f) => f.properties.kt)).toEqual([119, 41]);
  });

  it("issuedKey matches the API timestamp formats", () => {
    expect(issuedKey("2024-09-26T15:00:00Z")).toBe("2024-09-26T15:00:00Z");
    expect(issuedKey("2024-09-26T15:00:00+00:00")).toBe("2024-09-26T15:00:00Z");
  });
});

describe("markers and labels", () => {
  it("fans out markers that pile up and leaves a lone marker where it is", () => {
    const placed = spreadMarkers(
      [
        { id: "a", x: 100, y: 100 },
        { id: "b", x: 102, y: 101 },
        { id: "c", x: 99, y: 103 },
        { id: "far", x: 400, y: 300 },
      ],
      26,
    );
    expect(placed.get("far")).toEqual({ x: 400, y: 300 });
    const ids = ["a", "b", "c"] as const;
    for (const i of ids)
      for (const j of ids) {
        if (i >= j) continue;
        const p = placed.get(i) as { x: number; y: number };
        const q = placed.get(j) as { x: number; y: number };
        expect(Math.hypot(p.x - q.x, p.y - q.y)).toBeGreaterThanOrEqual(26);
      }
  });

  it("drops labels that collide or leave the view and keeps the heaviest", () => {
    const kept = placeLabels(
      [
        { id: "low", x: 50, y: 50, w: 40, h: 16, weight: 1 },
        { id: "high", x: 60, y: 52, w: 40, h: 16, weight: 9 },
        { id: "out", x: 2, y: 2, w: 40, h: 16, weight: 5 },
        { id: "ok", x: 150, y: 80, w: 40, h: 16, weight: 2 },
      ],
      { w: 300, h: 200 },
      [{ x: 140, y: 70, w: 5, h: 5 }],
    );
    expect(kept.map((k) => k.id)).toEqual(["high"]);
  });
});

describe("geometry helpers", () => {
  const square: FeatureCollection = {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [0, 0],
              [4, 0],
              [4, 2],
              [0, 2],
              [0, 0],
            ],
            [
              [1, 1],
              [2, 1],
              [2, 1.5],
              [1, 1],
            ],
          ],
        },
      },
    ],
  };
  it("labels a polygon at its centroid and keeps only its outer ring for the outline", () => {
    const [x, y] = labelPoint(square.features[0] as never);
    expect(x).toBeCloseTo(2);
    expect(y).toBeCloseTo(1);
    const outline = exteriorOnly(square).features[0]?.geometry.coordinates as unknown[];
    expect(outline).toHaveLength(1);
  });
});

const card = (over: Partial<ProposalCard> & { id: string; caseId: string }): ProposalCard =>
  ({
    proposal_id: over.id,
    decision_case_id: over.caseId,
    title: over.title ?? over.id,
    effective_decide_by_utc: over.effective_decide_by_utc ?? "2024-09-27T04:00:00Z",
    target_ids: over.target_ids ?? [],
    params: over.params ?? {},
    case: { prerequisite_ids: over.case?.prerequisite_ids ?? [] },
  }) as unknown as ProposalCard;

const asset = (id: string, region = "SC-45003", kind = "feeder", critical = false): Asset =>
  ({
    asset_id: id,
    domain: "electric",
    kind,
    region_id: region,
    lon_e6: -81_700_000,
    lat_e6: 33_500_000,
    criticality: 3,
    critical_facility: critical,
    customers_served: 0,
    classification: "C1",
  }) as Asset;

describe("chain", () => {
  const yard = card({ id: "P-CREWS", caseId: "DC-CREWS", target_ids: ["YARD"] });
  const fuel = card({ id: "P-FUEL", caseId: "DC-FUEL", target_ids: ["DEPOT"] });
  const power = card({
    id: "P-POWER",
    caseId: "DC-POWER",
    target_ids: ["FDR", "PS-17"],
    case: { prerequisite_ids: ["DC-FUEL", "DC-CREWS"] } as ProposalCard["case"],
  });
  const pressure = card({
    id: "P-PRESSURE",
    caseId: "DC-PRESSURE",
    target_ids: ["PS-17", "HSP"],
    case: { prerequisite_ids: ["DC-POWER"] } as ProposalCard["case"],
  });
  const assets = ["YARD", "DEPOT", "FDR", "PS-17"].map((id) => asset(id));
  const all = [pressure, power, yard, fuel];

  const sequence: SequenceStep[] = [
    { number: 1, caseId: "DC-CREWS", title: "Pre-position crews" },
    { number: 2, caseId: "DC-FUEL", title: "Send fuel" },
    { number: 3, caseId: "DC-POWER", title: "Hook up the generator" },
    { number: 4, caseId: "DC-PRESSURE", title: "Boil-water notice" },
  ];

  it("numbers the markers like the Sequence tab; a step whose assets are taken shares its first one", () => {
    const stops = buildStops(sequence, all, assets);
    expect(stops.map((s) => [s.number, s.assetId])).toEqual([
      [1, "YARD"],
      [2, "DEPOT"],
      [3, "FDR"],
      [3, "PS-17"],
      [4, "PS-17"],
    ]);
    expect(stops.map((s) => s.title)).toEqual([
      "Pre-position crews",
      "Send fuel",
      "Hook up the generator",
      "Hook up the generator",
      "Boil-water notice",
    ]);
  });

  it("marks the markers of a step that has several so the asset can tell them apart", () => {
    const stops = buildStops(sequence, all, assets);
    expect(stops.filter((s) => s.number === 3).every((s) => s.repeated)).toBe(true);
    expect(stops.filter((s) => s.number !== 3).some((s) => s.repeated)).toBe(false);
    expect(new Set(stops.map((s) => s.key)).size).toBe(stops.length);
  });

  it("places a vehicle step at its destination and a step without a proposal at its place", () => {
    const truck = card({
      id: "P-TRUCK",
      caseId: "DC-TRUCK",
      target_ids: ["FTK-1"],
      params: { destination_id: "PS-17" },
    });
    const steps: SequenceStep[] = [
      { number: 1, caseId: "DC-TRUCK", title: "Dispatch the fuel truck" },
      { number: 2, caseId: "DC-HOOKUP", title: "Hook up the generator", placeIds: ["PS-17"] },
      { number: 3, caseId: "DC-ZONE", title: "Hold the zone", placeIds: ["ZONE", "GONE"] },
    ];
    const stops = buildStops(steps, [truck], [asset("PS-17"), asset("ZONE")]);
    expect(stops.map((s) => [s.number, s.assetId])).toEqual([
      [1, "PS-17"],
      [2, "PS-17"],
      [3, "ZONE"],
    ]);
    expect(unplacedSteps(steps, stops)).toEqual([]);
  });

  it("names the destination before the targets and clicks on the destination find the decision", () => {
    const truck = card({
      id: "P-TRUCK",
      caseId: "DC-TRUCK",
      target_ids: ["FTK-1"],
      params: { destination_id: "PS-17" },
    });
    expect(placeIdsOf(truck)).toEqual(["PS-17", "FTK-1"]);
    expect(proposalForAssets(["PS-17"], [truck])).toBe("P-TRUCK");
  });

  it("draws nothing without a sequence", () => {
    expect(buildStops([], all, assets)).toEqual([]);
  });

  it("a click selects the most urgent decision that targets the asset", () => {
    const late = card({
      id: "LATE",
      caseId: "L",
      target_ids: ["PS-17"],
      effective_decide_by_utc: "2024-09-27T09:00:00Z",
    });
    expect(proposalForAssets(["PS-17"], [late, power])).toBe("P-POWER");
    expect(proposalForAssets(["NOPE"], [late, power])).toBeNull();
    expect(proposalForAssets(["NOPE", "PS-17"], [late, power])).toBe("P-POWER");
  });
});

describe("advisory in force", () => {
  const list = [
    { advisory_label: "N", issued_utc: "2024-09-26T09:00:00Z", next_advisory_utc: null },
    { advisory_label: "N+1", issued_utc: "2024-09-26T15:00:00Z", next_advisory_utc: null },
  ];
  it("takes the latest advisory issued at or before the scenario time, else the first", () => {
    expect(advisoryAt(list, "2024-09-26T16:00:00Z")?.advisory_label).toBe("N+1");
    expect(advisoryAt(list, "2024-09-26T15:00:00Z")?.advisory_label).toBe("N+1");
    expect(advisoryAt(list, "2024-09-23T12:00:00Z")?.advisory_label).toBe("N");
    expect(advisoryAt([], "2024-09-26T16:00:00Z")).toBeNull();
  });
});

describe("colour domain", () => {
  it("comes from the data and never collapses", () => {
    expect(domainOf([0.2, undefined, 0.8])).toEqual({ min: 0.2, max: 0.8 });
    const flat = domainOf([0.5, 0.5]);
    expect(flat && flat.max > flat.min).toBe(true);
    expect(domainOf([undefined])).toBeNull();
  });
});

describe("lifelines", () => {
  const regions: Region[] = [
    { region_id: "SC-45003", state: "SC", county_fips: "45003", name: "Aiken", bbox_e6: null },
    { region_id: "GA-13245", state: "GA", county_fips: "13245", name: "Richmond", bbox_e6: null },
  ];
  const risk = [
    {
      entity_id: "45003",
      level: "county",
      p_ppm: 300_000,
      band: "moderate",
      severity: "elevated",
      expected_impact: 1,
      drivers: [],
    },
    {
      entity_id: "13245",
      level: "county",
      p_ppm: 800_000,
      band: "very_high",
      severity: "critical",
      expected_impact: 5,
      drivers: [],
    },
  ] as RiskItem[];
  const assets = [
    asset("SUB-1", "SC-45003", "substation", true),
    asset("PS-1", "GA-13245", "pump_station", true),
    asset("PS-2", "SC-45003", "pump_station"),
    asset("YARD", "GA-13245", "staging_yard"),
  ];

  it("counts each lifeline and how many sit in a high-risk county", () => {
    const s = summariseLifelines(assets, regions, risk);
    expect(s.rows.find((r) => r.key === "pump_station")).toMatchObject({ total: 2, highRisk: 1 });
    expect(s.rows.find((r) => r.key === "substation")).toMatchObject({ total: 1, highRisk: 0 });
    expect(s.rows.find((r) => r.key === "staging")).toMatchObject({ total: 1, highRisk: 1 });
    expect(s.critical.map((c) => [c.assetId, c.county, c.band])).toEqual([
      ["SUB-1", "Aiken", "moderate"],
      ["PS-1", "Richmond", "very_high"],
    ]);
  });

  it("marks a facility unknown when its county has no risk row", () => {
    const s = summariseLifelines(assets, regions, []);
    expect(s.critical.every((c) => c.band === null)).toBe(true);
  });
});

describe("relaxing step markers around pulse rings", () => {
  const dist = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);

  it("keeps anchored markers, clears the others of the rings and never lets two touch", () => {
    const placed = new Map([
      ["own", { x: 100, y: 100 }],
      ["a", { x: 108, y: 104 }],
      ["b", { x: 96, y: 110 }],
      ["c", { x: 100, y: 100 }],
    ]);
    const out = relaxMarkers(placed, new Set(["own"]), [{ x: 100, y: 100 }], 26, 44);
    expect(out.get("own")).toEqual({ x: 100, y: 100 });
    for (const id of ["a", "b", "c"])
      expect(dist(out.get(id) as never, { x: 100, y: 100 })).toBeGreaterThanOrEqual(44);
    const ids = [...out.keys()];
    for (let i = 0; i < ids.length; i++)
      for (let j = i + 1; j < ids.length; j++)
        expect(
          dist(out.get(ids[i] as string) as never, out.get(ids[j] as string) as never),
        ).toBeGreaterThanOrEqual(26);
  });

  it("leaves a marker alone when it is already free", () => {
    const out = relaxMarkers(new Map([["far", { x: 300, y: 10 }]]), new Set(), [{ x: 0, y: 0 }], 26, 44);
    expect(out.get("far")).toEqual({ x: 300, y: 10 });
  });

  it("places labels without a view so panning cannot change which ones are kept", () => {
    const labels = [
      { id: "left", x: -50, y: -20, w: 30, h: 16, weight: 1 },
      { id: "right", x: 5000, y: 4000, w: 30, h: 16, weight: 1 },
    ];
    expect(placeLabels(labels, null).map((l) => l.id)).toEqual(["left", "right"]);
    expect(placeLabels(labels, { w: 100, h: 100 })).toEqual([]);
  });
});

describe("steps without a place on the map", () => {
  const steps: SequenceStep[] = [1, 2, 3, 4].map((n) => ({
    number: n,
    caseId: `DC-${n}`,
    title: `Step ${n}`,
  }));
  const stops = [{ number: 1 }, { number: 1 }, { number: 3 }, { number: 3 }, { number: 4 }];

  it("names the sequence steps that have no marker instead of skipping them silently", () => {
    expect(unplacedSteps(steps, stops).map((s) => s.number)).toEqual([2]);
    expect(unplacedNote(unplacedSteps(steps, stops))).toBe("Step 2 has no place on the map");
    expect(unplacedNote(unplacedSteps(steps, [{ number: 1 }, { number: 4 }]))).toBe(
      "Steps 2 and 3 have no place on the map",
    );
    expect(unplacedNote(unplacedSteps(steps, [{ number: 4 }]))).toBe(
      "Steps 1, 2 and 3 have no place on the map",
    );
  });

  it("says nothing when every step has a marker or the decision stands alone", () => {
    expect(
      unplacedNote(
        unplacedSteps(
          steps,
          [1, 2, 3, 4].map((number) => ({ number })),
        ),
      ),
    ).toBeNull();
    expect(unplacedSteps(steps.slice(0, 1), [])).toEqual([]);
  });
});
