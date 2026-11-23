import { approvalLabel } from "./approval";

describe("approvalLabel", () => {
  it("reads each tier as what it asks of people", () => {
    expect(["T0", "T1", "T2", "T3", "T4"].map(approvalLabel)).toEqual([
      "View only",
      "1 person confirms",
      "1 team signs",
      "2 teams sign",
      "Outside SGW",
    ]);
  });
  it("leaves an unknown tier as written", () => {
    expect(approvalLabel("T9")).toBe("T9");
  });
});
