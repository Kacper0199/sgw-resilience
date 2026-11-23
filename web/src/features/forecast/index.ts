import { defineFeature } from "@/app/defineFeature";

export const feature = defineFeature("forecast", () => import("./ForecastPage"));
