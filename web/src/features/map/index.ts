import { defineFeature } from "@/app/defineFeature";

export const feature = defineFeature("map", () => import("./MapPage"));
