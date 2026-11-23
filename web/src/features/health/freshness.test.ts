import { describe, expect, it } from "vitest";
import { measured } from "./format";

const feed = {
  source_id: "fsm-crews",
  feed_mode: "synthetic" as const,
  ingest_lag_s: 300,
  product_age_s: 17_700,
  freshness_limit_s: 900,
  stale: false,
};

describe("feed freshness", () => {
  it("compares a feed that reports on change by how late its data arrived, not by its age", () => {
    expect(measured({ ...feed, measured_by: "delay" })).toEqual({ seconds: 300, text: "5 min delay" });
  });

  it("compares a feed that reports on a schedule by the age of its newest data", () => {
    expect(measured({ ...feed, measured_by: "age" })).toEqual({ seconds: 17_700, text: "5 h" });
    expect(measured(feed)).toEqual({ seconds: 17_700, text: "5 h" });
  });

  it("says when nothing has arrived", () => {
    expect(measured({ ...feed, ingest_lag_s: null, product_age_s: null, measured_by: "delay" })).toEqual({
      seconds: null,
      text: "No data yet",
    });
  });
});
