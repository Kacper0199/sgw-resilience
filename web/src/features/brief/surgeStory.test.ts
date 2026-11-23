import { surgeMoment, surgeSpread, surgeStory } from "./surgeStory";

describe("surgeStory", () => {
  it("is empty without surges", () => {
    expect(surgeStory([])).toBeNull();
  });
  it("counts the counties that started together and the total", () => {
    const story = surgeStory([
      "2024-09-26T14:00:00Z",
      "2024-09-26T14:30:00Z",
      "2024-09-26T20:00:00Z",
      "2024-09-27T02:00:00Z",
    ]);
    expect(story).toEqual({
      total: 4,
      first: { count: 2, at: "2024-09-26T14:00:00.000Z" },
      latest: "2024-09-27T02:00:00.000Z",
    });
  });
  it("has no latest time when every surge began together", () => {
    expect(surgeStory(["2024-09-26T14:00:00Z", "2024-09-26T14:20:00Z"])?.latest).toBeNull();
  });
  it("leaves the day out for a time on the same day", () => {
    expect(surgeMoment("2024-09-26T20:00:00Z", "2024-09-26T14:00:00Z")).toBe("16:00 ET");
    expect(surgeMoment("2024-09-27T06:00:00Z", "2024-09-26T14:00:00Z")).toBe("Sep 27 02:00 ET");
  });
  it("keeps the first detection fixed while surges end and new ones start (R34 V1-19)", () => {
    const first = "2024-09-23T22:00:00Z";
    const atN1 = surgeSpread([first, "2024-09-26T09:00:00Z"], [first, "2024-09-26T09:00:00Z"]);
    const later = surgeSpread(
      [first, "2024-09-26T09:00:00Z", "2024-09-27T08:00:00Z"],
      ["2024-09-27T08:00:00Z"],
    );
    expect(atN1?.first.at).toBe("2024-09-23T22:00:00.000Z");
    expect(later?.first.at).toBe("2024-09-23T22:00:00.000Z");
    expect(later?.total).toBe(1);
    expect(later?.latest).toBe("2024-09-27T08:00:00.000Z");
  });
});
