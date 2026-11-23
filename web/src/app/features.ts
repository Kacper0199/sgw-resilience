import type { FeatureModule } from "./defineFeature";

const found = import.meta.glob<{ feature?: FeatureModule }>("../features/*/index.ts", { eager: true });

export const FEATURES: ReadonlyMap<string, FeatureModule> = new Map(
  Object.values(found)
    .map((m) => m.feature)
    .filter((f): f is FeatureModule => Boolean(f))
    .map((f) => [f.key, f]),
);
