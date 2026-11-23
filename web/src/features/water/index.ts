import { defineFeature } from "@/app/defineFeature";

export const feature = defineFeature("water", () => import("./WaterPage"));
