import { formatAbsolute, formatDuration, formatETOn, formatEtZ, formatRelative, urgencyOf } from "./time";

const NOW = "2024-09-27T01:00:00Z";

describe("time helpers", () => {
  it("adds the day to a time on another ET day than the scenario clock", () => {
    expect(formatETOn("2024-09-30T14:30:00Z", "2024-09-30T12:00:00Z")).toBe("10:30 ET");
    expect(formatETOn("2024-09-28T19:45:00Z", "2024-09-30T12:00:00Z")).toBe("Sep 28 15:45 ET");
    expect(formatETOn("2024-09-27T03:30:00Z", "2024-09-27T04:30:00Z")).toBe("Sep 26 23:30 ET");
    expect(formatETOn("2024-09-27T09:00:00Z", null)).toBe("Sep 27 05:00 ET");
  });

  it("formats ET first and UTC second", () => {
    expect(formatEtZ("2024-09-27T03:29:00Z")).toBe("23:29 ET (03:29Z)");
    expect(formatAbsolute("2024-09-27T03:29:00Z")).toBe("23:29 ET (03:29Z)");
  });
  it("formats durations without zero units", () => {
    expect(formatDuration(190)).toBe("3 h 10 m");
    expect(formatDuration(120)).toBe("2 h");
    expect(formatDuration(45)).toBe("45 m");
  });
  it("switches to days and hours from 48 hours", () => {
    expect(formatDuration(47 * 60 + 30)).toBe("47 h 30 m");
    expect(formatDuration(83 * 60 + 45)).toBe("3 d 11 h");
    expect(formatDuration(72 * 60)).toBe("3 d");
    expect(formatRelative("2024-09-30T13:00:00Z", NOW)).toBe("in 3 d 12 h");
  });
  it("formats relative times in both directions", () => {
    expect(formatRelative("2024-09-27T04:10:00Z", NOW)).toBe("in 3 h 10 m");
    expect(formatRelative("2024-09-27T00:30:00Z", NOW)).toBe("30 m ago");
  });
  it("marks urgency under 60 minutes and when missed", () => {
    expect(urgencyOf("2024-09-27T01:40:00Z", NOW)).toBe("soon");
    expect(urgencyOf("2024-09-27T04:00:00Z", NOW)).toBe("normal");
    expect(urgencyOf("2024-09-27T00:59:00Z", NOW)).toBe("missed");
  });
});
