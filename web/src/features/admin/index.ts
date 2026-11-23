import { defineFeature } from "@/app/defineFeature";

export const feature = defineFeature("admin", () => import("./AdminPage"));
