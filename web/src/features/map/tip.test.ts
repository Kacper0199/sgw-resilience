import { describe, expect, it } from "vitest";
import { chooseTipSide, edgeShift, TIP_EDGE, tipWidth } from "./tip";

describe("edgeShift", () => {
  it("leaves a tip that fits alone", () => {
    expect(edgeShift(100, 300, 800)).toBe(0);
  });

  it("moves a tip cut off on the left in from the edge", () => {
    expect(edgeShift(-40, 160, 800)).toBe(40 + TIP_EDGE);
  });

  it("moves a tip cut off on the right in from the edge", () => {
    expect(edgeShift(600, 830, 800)).toBe(-(30 + TIP_EDGE));
  });
});

describe("chooseTipSide", () => {
  const view = { w: 800, h: 600 };
  const tip = { w: 120, h: 26 };
  const marker = { x: 400, y: 300, w: 26, h: 26 };

  it("puts the tip above a lone marker", () => {
    expect(chooseTipSide(marker, [], tip, view)).toEqual({ side: "above", away: 0 });
  });

  it("moves to the next free side when a neighbour sits where the tip would go", () => {
    const above = { x: 400, y: 250, w: 26, h: 26 };
    expect(chooseTipSide(marker, [above], tip, view)).toEqual({ side: "below", away: 0 });
    const below = { x: 400, y: 350, w: 26, h: 26 };
    expect(chooseTipSide(marker, [above, below], tip, view)).toEqual({ side: "right", away: 0 });
  });

  it("moves out of a crowd until the tip covers nothing", () => {
    const crowd = [
      { x: 380, y: 270, w: 26, h: 26 },
      { x: 400, y: 330, w: 26, h: 26 },
      { x: 340, y: 300, w: 26, h: 26 },
      { x: 460, y: 300, w: 26, h: 26 },
    ];
    expect(chooseTipSide(marker, crowd, tip, view)).toEqual({ side: "above", away: 30 });
  });

  it("stays inside the map", () => {
    expect(chooseTipSide({ x: 400, y: 4, w: 26, h: 26 }, [], tip, view).side).toBe("below");
    expect(chooseTipSide({ x: 780, y: 300, w: 26, h: 26 }, [], tip, view).side).toBe("left");
  });

  it("sizes the tip from its text up to 280 px", () => {
    expect(tipWidth("2. Send fuel")).toBeLessThan(120);
    expect(tipWidth("x".repeat(200))).toBe(280);
  });
});
