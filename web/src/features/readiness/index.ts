import { defineFeature } from "@/app/defineFeature";

export const feature = defineFeature("readiness", () => import("./ReadinessPage"));
