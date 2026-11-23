import type { components } from "@/contracts/api.gen";

type Schemas = components["schemas"];
export type HeatView = Schemas["HazardLibraryHeat"];
export type WildfireView = Schemas["HazardLibraryWildfire"];
export type HazardAction = Schemas["HazardAction"];
export type HazardSource = Schemas["HazardSource"];
export type HeatUnit = Schemas["HeatUnit"];
export type CircuitRisk = Schemas["CircuitRisk"];
