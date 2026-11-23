import { defineFeature } from "@/app/defineFeature";

export const feature = defineFeature("brief", () => import("./BriefPage"));
