import { createBrowserRouter, type RouteObject } from "react-router";
import { LoginPage } from "@/auth/LoginPage";
import { RequireAuth } from "@/auth/RequireAuth";
import { PACK_PAGES } from "@/lib/scenarios";
import { FEATURES } from "./features";
import { Shell } from "./layout/Shell";
import { ModulePlaceholder } from "./ModulePlaceholder";
import { MODULES } from "./modules";
import { gated, HELENE_ONLY } from "./ScenarioGate";

function moduleRoute(def: (typeof MODULES)[number]): RouteObject {
  const index = def.path === "/";
  const route: RouteObject = index ? { index: true } : { path: def.path.slice(1) };
  if (def.key === "help") {
    return { ...route, lazy: async () => ({ Component: (await import("./HelpPage")).default }) };
  }
  const feature = FEATURES.get(def.key);
  if (feature) {
    return {
      ...route,
      lazy: async () => {
        const Page = (await feature.load()).default;
        return { Component: HELENE_ONLY.has(def.key) && !PACK_PAGES.has(def.key) ? gated(def, Page) : Page };
      },
    };
  }
  return { ...route, Component: ModulePlaceholder };
}

const HydrateFallback = () => (
  <div role="status" className="grid h-full place-items-center text-[13px] text-muted">
    Loading…
  </div>
);

const devRoutes: RouteObject[] = import.meta.env.DEV
  ? [
      {
        path: "/design-check",
        HydrateFallback,
        lazy: async () => ({ Component: (await import("./design-check/DesignCheckPage")).default }),
      },
    ]
  : [];

export const routes: RouteObject[] = [
  ...devRoutes,
  { path: "/login", Component: LoginPage, HydrateFallback },
  {
    Component: RequireAuth,
    HydrateFallback,
    children: [
      {
        Component: Shell,
        children: [
          ...MODULES.map(moduleRoute),
          {
            path: "decisions/:proposalId",
            lazy: async () => ({ Component: (await import("@/features/decisions/CasePage")).default }),
          },
          { path: "*", Component: ModulePlaceholder },
        ],
      },
    ],
  },
];

export const createAppRouter = () => createBrowserRouter(routes);
