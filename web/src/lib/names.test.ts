import { assetLabel, assetName, crewName, plainIds, zoneName } from "./names";

describe("names", () => {
  it("reads a crew as its bird and number", () => {
    expect(crewName("CRW-KESTREL-0101")).toBe("Kestrel 1");
    expect(crewName("CRW-KESTREL-02")).toBe("Kestrel 2");
    expect(crewName("CRW-GROSBEAK-0210")).toBe("Grosbeak 10");
    expect(crewName("CRW-MA-TALON-11")).toBe("Talon 11");
  });

  it("reads zones, hospitals and yards as plain names", () => {
    expect(zoneName("WZ-PS17-CEDARFALL")).toBe("Cedarfall");
    expect(assetName("HSP-AIK-TALLOWBRANCH")).toBe("Tallowbranch hospital");
    expect(assetName("STG-RCH-MILLPOND-YARD")).toBe("Millpond yard");
    expect(assetName("GEN-PS52-DEERWATER")).toBe("Deerwater generator");
    expect(assetName("PS-17")).toBe("PS-17");
    expect(assetName("FTK-WREN-3")).toBe("Fuel truck Wren 3");
    expect(assetName("WTK-CORDGRASS-2")).toBe("Water tanker Cordgrass 2");
    expect(assetName("CHM-TERN-2")).toBe("Hypochlorite truck Tern 2");
  });

  it("reads the exercise facilities as plain names", () => {
    expect(assetName("SHL-AIK-THISTLECROFT")).toBe("Thistlecroft shelter");
    expect(assetName("NRS-AIK-ROSEWILD-PINES")).toBe("Rosewild Pines care home");
    expect(assetName("LS-RCH-BUTTONBUSH-CREEK")).toBe("Buttonbush Creek lift station");
    expect(assetName("POD-AIK-OXBOW-RUN")).toBe("Oxbow Run water distribution point");
    expect(plainIds("Tanker for DLY-AIK-MARROWSTONE")).toBe("Tanker for the Marrowstone dialysis center");
  });

  it("reads transformers and feeders as plain names", () => {
    expect(assetName("DT-AIK-2238-COPPERLEAF")).toBe("Copperleaf transformer");
    expect(assetName("TX-BRAMBLEGATE-T2")).toBe("Bramblegate transformer 2");
    expect(assetName("FDR-PICS-2218")).toBe("Feeder 2218");
  });

  it("rewrites identifiers inside a sentence", () => {
    expect(plainIds("Run the overdue annual load test on GEN-PS52-DEERWATER")).toBe(
      "Run the overdue annual load test on the Deerwater generator",
    );
    expect(plainIds("Confirm the STG-AIK-SANDHILL-YARD lease and fuel-on-site terms")).toBe(
      "Confirm the Sandhill yard lease and fuel-on-site terms",
    );
    expect(plainIds("Renew the MOU with the Talon task force (CRW-MA-TALON-11)")).toBe(
      "Renew the MOU with the Talon task force",
    );
    expect(plainIds("Clear vegetation on the FDR-AIK-2207 (PS-17) trunks")).toBe(
      "Clear vegetation on the feeder 2207 (PS-17) trunks",
    );
    expect(plainIds("Sign an agreement for HSP-AIK-TALLOWBRANCH")).toBe(
      "Sign an agreement for Tallowbranch hospital",
    );
  });
});

describe("plainIds feeders", () => {
  it("does not repeat the word feeder", () => {
    expect(plainIds("Feeder FDR-AIK-2207")).toBe("Feeder 2207");
  });
});

describe("assetLabel", () => {
  it("names a pressure zone like the Water page and leaves other assets as the API names them", () => {
    expect(
      assetLabel({
        asset_id: "WZ-PS17-CEDARFALL",
        name: "Cedarfall water zone (synthetic)",
        kind: "pressure_zone",
      }),
    ).toBe("Cedarfall zone");
    expect(
      assetLabel({ asset_id: "PS-17", name: "PS-17 Cedarfall booster (synthetic)", kind: "pump_station" }),
    ).toBe("PS-17 Cedarfall booster (synthetic)");
    expect(assetLabel({ asset_id: "PS-99" })).toBe("PS-99");
  });
});
