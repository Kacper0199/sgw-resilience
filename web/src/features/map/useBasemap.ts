import { useQuery } from "@tanstack/react-query";
import { geoUrl } from "./basemap";
import type { FeatureCollection } from "./geo";

export interface Basemap {
  land: FeatureCollection;
  states: FeatureCollection;
  lakes: FeatureCollection;
}

async function load(name: string): Promise<FeatureCollection> {
  const res = await fetch(geoUrl(name));
  if (!res.ok) throw new Error(`${name} ${res.status}`);
  return res.json();
}

/** Natural Earth land, US states and big lakes (public domain), served from `public/geo`. */
export const useBasemap = () =>
  useQuery({
    queryKey: ["geo", "basemap"],
    queryFn: async (): Promise<Basemap> => {
      const [land, states, lakes] = await Promise.all([
        load("land.geo.json"),
        load("states.geo.json"),
        load("lakes.geo.json"),
      ]);
      return { land, states, lakes };
    },
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
