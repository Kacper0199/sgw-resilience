import { defineFeature } from "@/app/defineFeature";

export const feature = defineFeature("crews", () => import("./CrewsPage"));
