import { describe, expect, it } from "vitest";
import { movedNote } from "./clockShifts";

const shift = (minutes: number) => ({
  caseId: "DC-X",
  from: "2024-09-27T03:15:00Z",
  to: new Date(Date.parse("2024-09-27T03:15:00Z") + minutes * 60_000).toISOString(),
  atMs: 0,
});

describe("moved deadline note (R35 V8-02)", () => {
  it("names the one decision in view whose deadline moved", () => {
    expect(movedNote([{ title: "Dispatch the fuel truck to PS-17", shift: shift(-76) }])).toBe(
      "Dispatch the fuel truck to PS-17: deadline moved earlier by 1 h 16 m",
    );
  });

  it("counts several moved decisions instead of naming one of them", () => {
    const moved = ["Pre-position crews", "Dispatch the fuel truck", "Secure water supply"].map((title) => ({
      title,
      shift: shift(-76),
    }));
    expect(movedNote(moved)).toBe("3 deadlines moved earlier by 1 h 16 m");
    const crews = { title: "Pre-position crews", shift: shift(-76) };
    expect(movedNote([crews, { title: "Other", shift: shift(-30) }])).toBe("2 deadlines moved earlier");
    expect(movedNote([crews, { title: "Other", shift: shift(30) }])).toBe("2 deadlines moved");
    expect(movedNote([])).toBeNull();
  });
});
