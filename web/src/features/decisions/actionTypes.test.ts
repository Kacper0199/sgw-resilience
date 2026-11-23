import { Fuel, Megaphone, MegaphoneOff, Truck, Zap } from "lucide-react";
import { actionMark, decisionTitle } from "./actionTypes";

describe("actionMark", () => {
  it("names every kind of decision in plain words", () => {
    expect(actionMark("boil_water_notice").label).toBe("Boil-water notice");
    expect(actionMark("lift_boil_water_notice").label).toBe("Lift a notice");
    expect(actionMark("cross_domain_priority").label).toBe("Restoration order");
    expect(actionMark("work_order_draft").label).toBe("Work order");
    expect(actionMark("boil_water_notice").Icon).toBe(Megaphone);
    expect(actionMark("lift_boil_water_notice").Icon).toBe(MegaphoneOff);
  });

  it("names the resource a resource order sends, falling back to the order itself", () => {
    expect(actionMark("field_resource_order", { resource_kind: "fuel" })).toMatchObject({
      label: "Fuel truck",
      Icon: Fuel,
    });
    expect(actionMark("field_resource_order", { resource_kind: "potable_water_tanker" }).label).toBe(
      "Water tanker",
    );
    expect(actionMark("field_resource_order", { resource_kind: "mobile_generator" })).toMatchObject({
      label: "Portable generator",
      Icon: Zap,
    });
    expect(actionMark("field_resource_order")).toMatchObject({ label: "Resource order", Icon: Truck });
    expect(actionMark("field_resource_order", { resource_kind: "unknown" }).label).toBe("Resource order");
  });

  it("names a priority decision that hooks up a generator as a generator hookup, not a restoration order", () => {
    expect(
      actionMark("cross_domain_priority", { generator_id: "MGEN-HALBERD-500", station_id: "PS-17" }),
    ).toMatchObject({ label: "Generator hookup", Icon: Zap });
    expect(actionMark("cross_domain_priority", { priority: ["FDR-AIK-2219"] }).label).toBe(
      "Restoration order",
    );
  });
});

describe("decisionTitle", () => {
  it("turns feeders, sections and vehicles in a server title into words", () => {
    expect(decisionTitle("Set the restoration order of FDR-AIK-2219 and FDR-AIK-2207")).toBe(
      "Set the restoration order of feeder 2219 and feeder 2207",
    );
    expect(decisionTitle("Patrol the dark AMI section FDR-AIK-2231-S3")).toBe(
      "Patrol the dark meter section 3 of feeder 2231",
    );
    expect(decisionTitle("Send portable generator MGEN-HALBERD-500 to PS-52")).toBe(
      "Send portable generator Halberd to PS-52",
    );
    expect(decisionTitle("Reroute fuel truck FTK-WREN-3 to PS-38")).toBe(
      "Reroute fuel truck Wren 3 to PS-38",
    );
  });

  it("leaves a title without identifiers as it is", () => {
    expect(decisionTitle("Issue a boil water advisory for the Laurelspur zone")).toBe(
      "Issue a boil water advisory for the Laurelspur zone",
    );
  });
});
