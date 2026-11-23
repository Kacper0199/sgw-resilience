import { timingLabels, timingText } from "./ui";

const BEFORE = { advisoriesOver: false };
const AFTER = { advisoriesOver: true };

describe("Timing on the scenario clock", () => {
  it("keeps the advisory words while advisories still come", () => {
    expect(timingText("decide_now", BEFORE)).toBe("Before next advisory");
    expect(timingText("wait_for_next_advisory", BEFORE)).toBe("Can wait");
    expect(timingText("act_now", BEFORE)).toBe("Act now");
  });

  it("gives act-or-wait advice only, never the distance the Deadline column already shows", () => {
    expect(timingText("act_now", AFTER)).toBe("Act now");
    expect(timingText("decide_now", AFTER)).toBeNull();
    expect(timingText("wait_for_next_advisory", AFTER)).toBeNull();
    expect(timingText("n/a", AFTER)).toBeNull();
    expect(timingText("n/a", BEFORE)).toBeNull();
  });

  it("never offers 'Before next advisory' as a filter once the advisories are over", () => {
    expect(Object.values(timingLabels(true))).not.toContain("Before next advisory");
    expect(timingLabels(false).decide_now).toBe("Before next advisory");
  });
});
