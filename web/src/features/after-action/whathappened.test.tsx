import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import observedData from "../map/mock/observed.gen.json";
import { declaredCounties, money, type OfficialRecord, WhatHappened } from "./WhatHappened";

const full = observedData.record as OfficialRecord;
const before: OfficialRecord = {
  ...full,
  declarations: [],
  events_total: 0,
  events_by_type: [],
  deaths: 0,
  injuries: 0,
  damage_usd: 0,
  top_events: [],
};

describe("What happened", () => {
  it("shows declarations, counts and the most severe reports with links to the official pages", () => {
    render(<WhatHappened record={full} />);
    const rows = screen.getAllByTestId("declaration-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0] as HTMLElement).getByRole("link", { name: "DR-4829-SC" })).toHaveAttribute(
      "href",
      "https://www.fema.gov/disaster/4829",
    );
    const events = screen.getAllByTestId("storm-event-row");
    expect(events.length).toBe(Math.min(5, full.top_events.length));
    expect(within(events[0] as HTMLElement).getByRole("link")).toHaveAttribute(
      "href",
      expect.stringContaining("eventdetails.jsp?id="),
    );
    expect(screen.getByRole("list", { name: "Storm reports by type" })).toHaveTextContent("Tropical Storm");
    expect(screen.getByText(/not endorsed by FEMA/)).toBeInTheDocument();
    expect(declaredCounties(full)).toBeGreaterThan(50);
  });

  it("before any declaration or report it says so in one line each", () => {
    render(<WhatHappened record={before} />);
    expect(screen.getByText("No federal disaster declaration yet.")).toBeInTheDocument();
    expect(screen.queryByTestId("storm-event-row")).toBeNull();
    expect(screen.getByText("None yet")).toBeInTheDocument();
  });

  it("money is short", () => {
    expect(money(1_858_011_500)).toBe("$1.86 B");
    expect(money(500_000_000)).toBe("$500 M");
    expect(money(19_200_000)).toBe("$19 M");
    expect(money(4_250_000)).toBe("$4.3 M");
    expect(money(2_000)).toBe("$2 K");
    expect(money(0)).toBe("—");
  });
});
