const titleCase = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();

const words = (segments: string[]) => segments.map(titleCase).join(" ");

const KIND_SUFFIX = {
  WZ: "",
  HSP: " hospital",
  STG: " yard",
  GEN: " generator",
  DEP: " fuel depot",
  SHL: " shelter",
  DLY: " dialysis center",
  NRS: " care home",
  ECC: " 911 center",
  WTP: " water treatment plant",
  LS: " lift station",
  POD: " water distribution point",
} as const;

/** "FTK-WREN-3" reads as "Fuel truck Wren 3", as the decision titles name it. */
const VEHICLE_KIND = { FTK: "Fuel truck", WTK: "Water tanker", CHM: "Hypochlorite truck" } as const;

const ID_PATTERN =
  /\b(?:WZ|HSP|STG|CRW|GEN|FDR|DEP|MGEN|DT|TX|SHL|DLY|NRS|ECC|WTP|LS|POD)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b/g;

/** "CRW-KESTREL-0101" reads as "Kestrel 1" and "CRW-MA-TALON-11" as "Talon 11": the bird, then the crew's number. */
export function crewName(crewId: string): string {
  const parts = crewId.split("-").slice(1);
  const last = parts.at(-1) ?? "";
  const number = /^\d+$/.test(last) ? Number(last.slice(-2)) : undefined;
  const label = parts.filter((p) => p !== "MA" && !/^\d+$/.test(p));
  return [words(label), number].filter((p) => p !== undefined && p !== "").join(" ") || crewId;
}

/** "WZ-PS17-CEDARFALL" reads as "Cedarfall". */
export const zoneName = (zoneId: string): string => words(zoneId.split("-").slice(2));

/** Yard place names written as one word in their identifiers, in the words the decision titles use. */
const YARD_PLACES: Record<string, string> = {
  REEDYSHOALS: "Reedy Shoals",
  ASHLEYFERRY: "Ashley Ferry",
  OGEECHEEWHARF: "Ogeechee Wharf",
  NORTHOCONEE: "North Oconee",
  LYNCHESRUN: "Lynches Run",
  OCONEEFLATS: "Oconee Flats",
  CONGAREEBEND: "Congaree Bend",
  OKEFENOKEEGATE: "Okefenokee Gate",
  CATAWBALANDING: "Catawba Landing",
};

/** "STG-AIK-SANDHILL-YARD" reads as "Sandhill yard", "STG-GVL-REEDYSHOALS-YARD" as "Reedy Shoals yard", with the county code kept beside it. */
export function yardName(yardId: string): { name: string; county: string } {
  const parts = yardId.split("-");
  const place = parts[2] ?? yardId;
  return { name: `${YARD_PLACES[place] ?? titleCase(place)} yard`, county: parts[1] ?? "" };
}

/**
 * An asset or crew identifier in words: "HSP-AIK-TALLOWBRANCH" is "Tallowbranch hospital", "WZ-PS17-CEDARFALL" is
 * "Cedarfall", "STG-RCH-MILLPOND-YARD" is "Millpond yard", "DT-AIK-2238-COPPERLEAF" is "Copperleaf transformer". Pump stations ("PS-17") and anything unknown stay as written.
 */
export function assetName(id: string): string {
  if (id === "SGW-ELECTRIC-TERRITORY") return "Whole service area";
  const prefix = id.split("-")[0] ?? "";
  if (prefix === "CRW") return crewName(id);
  if (prefix === "FDR") return `Feeder ${id.split("-").at(-1)}`;
  if (prefix === "TX") {
    const parts = id.split("-");
    return `${words(parts.slice(1, -1))} transformer ${(parts.at(-1) ?? "").replace(/^T/, "")}`;
  }
  if (prefix === "DT") return `${words(id.split("-").slice(3))} transformer`;
  if (prefix === "MGEN") return `${words(id.split("-").slice(1, -1))} generator`;
  if (prefix in VEHICLE_KIND) {
    const parts = id.split("-").slice(1);
    const number = /^\d+$/.test(parts.at(-1) ?? "") ? ` ${parts.pop()}` : "";
    return `${VEHICLE_KIND[prefix as keyof typeof VEHICLE_KIND]} ${words(parts)}${number}`;
  }
  if (prefix === "STG") return yardName(id).name;
  if (id.endsWith("-TERRITORY")) return `${words(id.split("-").slice(1, -1))} service territory`;
  if (prefix === "GEN") return `${words(id.split("-").slice(2))} generator`;
  if (prefix in KIND_SUFFIX) {
    const kind = KIND_SUFFIX[prefix as keyof typeof KIND_SUFFIX];
    return `${words(id.split("-").slice(2))}${kind}`;
  }
  return id;
}

/** The name an asset shows on the map: a pressure zone as "Cedarfall zone", every other asset as the API names it. */
export function assetLabel(asset: { asset_id: string; name?: string | null; kind?: string }): string {
  if (asset.kind === "pressure_zone" && asset.asset_id.startsWith("WZ-"))
    return `${assetName(asset.asset_id)} zone`;
  return asset.name ?? asset.asset_id;
}

const NEEDS_ARTICLE = /\b(?:on|at|of|for|with|to)\s$/;

/** Server sentences that mention assets by identifier, rewritten with their plain names. */
export function plainIds(text: string): string {
  const withoutEcho = text.replace(/\s*\((?:CRW|STG|HSP|WZ)-[A-Z0-9-]+\)/g, "");
  return withoutEcho.replace(ID_PATTERN, (id, offset: number, whole: string) => {
    const name = assetName(id);
    const before = whole.slice(0, offset);
    const proper = /^(?:WZ|HSP|CRW|STG)-/.test(id);
    if (id.startsWith("FDR-")) {
      if (/\bfeeder\s$/i.test(before)) return name.replace(/^Feeder /, "");
      return offset === 0 || /[.!?]\s$/.test(before) ? name : name.toLowerCase();
    }
    if (!proper && NEEDS_ARTICLE.test(before)) return `the ${name}`;
    return name;
  });
}
