import { defineFeature } from "@/app/defineFeature";

export const feature = defineFeature("after_action", () => import("./AfterActionPage"));
