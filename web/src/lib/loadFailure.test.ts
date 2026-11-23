import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { loadFailure, loadFailureLine, loadFailureTitle } from "./loadFailure";

const forbidden = new ApiError(403, "WATER_DOMAIN_REQUIRED", "the boil-water register is shown to water", {});
const down = new ApiError(503, "POLICY_UNAVAILABLE", "x", {});

describe("loadFailure", () => {
  it("reads 403 as no access and everything else as a failed load", () => {
    expect(loadFailure(forbidden)).toBe("no_access");
    expect(loadFailure(down)).toBe("failed");
    expect(loadFailure(new TypeError("Failed to fetch"))).toBe("failed");
  });

  it("words the list and key-number states in plain words, never the server message", () => {
    expect(loadFailureTitle(forbidden, "boil-water notices")).toBe(
      "You don't have access to boil-water notices.",
    );
    expect(loadFailureTitle(down, "boil-water notices")).toBe("Couldn't load boil-water notices.");
    expect(loadFailureLine(forbidden)).toBe("You don't have access");
    expect(loadFailureLine(down)).toBe("Couldn't load");
  });
});
