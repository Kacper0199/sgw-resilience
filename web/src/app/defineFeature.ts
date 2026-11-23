import type { ComponentType } from "react";
import type { ModuleDef } from "./modules";

export interface FeatureModule {
  key: ModuleDef["key"];
  load: () => Promise<{ default: ComponentType }>;
}

/** A feature declares itself in `features/<name>/index.ts`; the router discovers it with import.meta.glob. */
export const defineFeature = (key: FeatureModule["key"], load: FeatureModule["load"]): FeatureModule => ({
  key,
  load,
});
