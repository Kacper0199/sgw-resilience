import { defineFeature } from "@/app/defineFeature";

export const feature = defineFeature("ask", () => import("./AskPage"));
