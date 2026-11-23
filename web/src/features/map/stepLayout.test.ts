import { describe, expect, it } from "vitest";
import { LAYOUT_RANGE, layoutSteps, layoutZoom, worldPixel } from "./stepLayout";

const stops = [
  { key: "1:a", assetId: "a", position: [-81.7, 33.55] as [number, number] },
  { key: "2:b", assetId: "b", position: [-81.701, 33.551] as [number, number] },
  { key: "3:c", assetId: "c", position: [-81.699, 33.549] as [number, number] },
  { key: "4:d", assetId: "d", position: [-80.5, 33.0] as [number, number] },
];
const rings = [{ id: "b", lon: -81.701, lat: 33.551 }];

describe("step badge layout", () => {
  it("is the same for every zoom inside one range and changes only across its boundary", () => {
    const low = layoutZoom(8.0);
    const same = [8.0, 8.1, 8.25, 8 + LAYOUT_RANGE - 0.001].map((z) => layoutSteps(stops, rings, z));
    for (const layout of same) expect(layout).toEqual(same[0]);
    expect(layoutZoom(8 + LAYOUT_RANGE - 0.001)).toBe(low);
    expect(layoutZoom(8 + LAYOUT_RANGE)).toBe(low + LAYOUT_RANGE);
    expect(layoutSteps(stops, rings, 9.2)).not.toEqual(same[0]);
  });

  it("does not depend on what came before: coming back to a zoom gives the same offsets", () => {
    const first = layoutSteps(stops, rings, 9.1);
    layoutSteps(stops, rings, 6.2);
    layoutSteps(stops, rings, 10);
    expect(layoutSteps(stops, rings, 9.1)).toEqual(first);
  });

  it("keeps the badges apart and off the pulse ring", () => {
    const { offsets, owners } = layoutSteps(stops, rings, 9.1);
    const at = (key: string) => {
      const s = stops.find((x) => x.key === key) as (typeof stops)[number];
      const p = worldPixel(s.position[0], s.position[1], layoutZoom(9.1));
      const o = offsets.get(key) as [number, number];
      return { x: p.x + o[0], y: p.y + o[1] };
    };
    const keys = stops.map((s) => s.key);
    for (let i = 0; i < keys.length; i++)
      for (let j = i + 1; j < keys.length; j++) {
        const a = at(keys[i] as string);
        const b = at(keys[j] as string);
        expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(24);
      }
    expect(owners.get("b")).toBe("2:b");
  });

  it("measures pixel differences between points the same wherever the map is centred", () => {
    const a = worldPixel(-81.7, 33.55, 9);
    const b = worldPixel(-81.5, 33.4, 9);
    expect(b.x - a.x).toBeCloseTo((0.2 / 360) * 512 * 2 ** 9, 5);
    expect(b.y).toBeGreaterThan(a.y);
  });
});
