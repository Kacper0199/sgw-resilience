/** Where the replay's data comes from, one line each; the full list with licences is `data/ATTRIBUTION.md`. */
export interface DataSource {
  key: string;
  what: string;
  source: string;
  licence: string;
  real: boolean;
}

export const DATA_SOURCES: readonly DataSource[] = [
  {
    key: "nhc",
    what: "Storm track, cone and advisories",
    source: "NOAA National Hurricane Center (HURDAT2, GIS archive AL092024)",
    licence: "Public domain",
    real: true,
  },
  {
    key: "asos",
    what: "Observed wind gusts",
    source: "NWS/FAA ASOS stations via the Iowa Environmental Mesonet",
    licence: "Public observations",
    real: true,
  },
  {
    key: "eaglei",
    what: "Past outages the forecast learned from",
    source: "EAGLE-I county outages, Oak Ridge National Laboratory",
    licence: "CC BY 4.0",
    real: true,
  },
  {
    key: "census",
    what: "Counties, land and coast distance",
    source: "US Census Bureau TIGER boundaries; CDC/ATSDR SVI 2022",
    licence: "Public domain",
    real: true,
  },
  {
    key: "ladi",
    what: "Aerial damage photos",
    source: "LADI v2, Civil Air Patrol imagery, MIT Lincoln Laboratory (2023 US events)",
    licence: "CC BY 4.0",
    real: true,
  },
  {
    key: "federal",
    what: "Federal guidance in the procedure library",
    source: "DOE Helene situation reports; EPA incident action checklists",
    licence: "Public domain",
    real: true,
  },
  {
    key: "sgw",
    what: "SGW grid, water, crews and procedures",
    source: "Synthetic, generated for this platform on the real storm",
    licence: "Apache-2.0",
    real: false,
  },
];

/** Where a scripted exercise's data comes from (R34 scenario packs): only the storm track and the counties are real. */
export const PACK_DATA_SOURCES: readonly DataSource[] = [
  {
    key: "nhc",
    what: "Storm track",
    source: "NOAA National Hurricane Center (HURDAT2 best track)",
    licence: "Public domain",
    real: true,
  },
  {
    key: "census",
    what: "Counties",
    source: "US Census Bureau TIGER boundaries",
    licence: "Public domain",
    real: true,
  },
  {
    key: "scripted",
    what: "Outages, decisions and crews",
    source: "Scripted exercise data",
    licence: "Synthetic",
    real: false,
  },
];
