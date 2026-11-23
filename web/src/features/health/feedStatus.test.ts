import { describe, expect, it } from "vitest";
import { feedStatus } from "./format";
import type { FeedHealthItem } from "./types";

const feed = (over: Partial<FeedHealthItem>): FeedHealthItem => ({
  source_id: "oms",
  feed_mode: "synthetic",
  ingest_lag_s: 30,
  product_age_s: 300,
  freshness_limit_s: 900,
  stale: false,
  ...over,
});

describe("feedStatus", () => {
  it("never calls a feed with nothing delivered on time", () => {
    expect(feedStatus(feed({ ingest_lag_s: null, product_age_s: null }))).toBe("no_data");
    expect(feedStatus(feed({ status: "no_data" }))).toBe("no_data");
  });

  it("keeps a quiet feed that reports on change apart from late and missing", () => {
    expect(feedStatus(feed({ status: "quiet", ingest_lag_s: null, product_age_s: null }))).toBe("quiet");
  });

  it("follows the server's status, else stale", () => {
    expect(feedStatus(feed({}))).toBe("on_time");
    expect(feedStatus(feed({ stale: true }))).toBe("late");
    expect(feedStatus(feed({ status: "late", stale: true }))).toBe("late");
  });
});
