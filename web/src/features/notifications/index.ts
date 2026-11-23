import { defineFeature } from "@/app/defineFeature";

export const feature = defineFeature("notifications", () => import("./NotificationsPage"));
