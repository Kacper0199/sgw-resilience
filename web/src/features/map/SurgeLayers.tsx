import { Layer, Marker, Source, useMap } from "@vis.gl/react-maplibre";
import { useMemo } from "react";
import { VALUE_LABEL_ZOOM } from "./basemap";
import type { FeatureCollection } from "./geo";
import type { SurgeLabel, SurgeStarts } from "./surges";
import { useMapSettled } from "./useMapSettled";
import type { useThemeColors } from "./useThemeColors";

export const SURGE_HIT = "surges-fill";
const LABEL_DY = 13;
const HALO = "0 0 3px var(--surface), 0 0 3px var(--surface), 0 0 2px var(--surface)";
const vis = (on: boolean) => ({ visibility: on ? ("visible" as const) : ("none" as const) });

const RECENT = ["==", ["get", "recent"], true] as never;

interface Props {
  on: boolean;
  outlines: FeatureCollection;
  labels: SurgeLabel[];
  starts: SurgeStarts | null;
  c: ReturnType<typeof useThemeColors>;
}

/** Start time to colour: earliest to latest along the surge ramp; one colour when they all began together. */
function startColour(starts: SurgeStarts | null, colours: string[]): unknown {
  const from = starts ? Date.parse(starts.first) : 0;
  const to = starts ? Date.parse(starts.last) : 0;
  if (to <= from) return colours[0];
  const step = (to - from) / (colours.length - 1);
  return [
    "interpolate",
    ["linear"],
    ["get", "onset"],
    ...colours.flatMap((col, i) => [from + step * i, col]),
  ];
}

/** Counties with an active outage surge: filled by when the surge began (earliest to latest), a dashed outline on
 * those that began in the last 3 hours (maplibre layers) and, zoomed in, the start time as a Marker under the
 * county's label point, so all of it stays pinned while the map moves. */
export function SurgeLayers({ on, outlines, labels, starts, c }: Props) {
  const { current } = useMap();
  const settled = useMapSettled();
  const zoomedIn = useMemo(() => {
    void settled;
    return (current?.getMap().getZoom() ?? 0) >= VALUE_LABEL_ZOOM;
  }, [current, settled]);
  return (
    <>
      <Source id="surges" type="geojson" data={outlines as never}>
        <Layer
          id={SURGE_HIT}
          type="fill"
          beforeId="county-lines"
          layout={vis(on)}
          paint={{ "fill-color": startColour(starts, c.surge) as never, "fill-opacity": 0.78 }}
        />
        <Layer
          id="surges-casing"
          type="line"
          filter={RECENT}
          layout={{ ...vis(on), "line-join": "round" }}
          paint={{ "line-color": c.surface, "line-width": 4, "line-opacity": 0.85 }}
        />
        <Layer
          id="surges-line"
          type="line"
          filter={RECENT}
          layout={{ ...vis(on), "line-join": "round" }}
          paint={{ "line-color": c.ink, "line-width": 1.8, "line-dasharray": [2, 1.4] }}
        />
      </Source>
      {on &&
        zoomedIn &&
        labels.map((l) => (
          <Marker
            key={l.id}
            longitude={l.lon}
            latitude={l.lat}
            offset={[0, LABEL_DY]}
            anchor="center"
            style={{ pointerEvents: "none" }}
          >
            <span
              data-testid="surge-start"
              data-pin={`${l.lon},${l.lat},0,${LABEL_DY}`}
              style={{ textShadow: HALO }}
              className="block text-[10.5px] leading-4 font-medium whitespace-nowrap text-ink-2 tnum"
            >
              {l.text}
            </span>
          </Marker>
        ))}
    </>
  );
}
