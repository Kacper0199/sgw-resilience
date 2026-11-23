import { defineFeature } from "@/app/defineFeature";

export const feature = defineFeature("decisions", () => import("./DecisionsPage"));
