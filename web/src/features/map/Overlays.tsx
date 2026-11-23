import { Marker, useMap } from "@vis.gl/react-maplibre";
import { useEffect, useMemo } from "react";
import { cn } from "@/lib/cn";
import { VALUE_LABEL_ZOOM } from "./basemap";
import type { ChainStop } from "./chain";
import { type LabelCandidate, placeLabels, type Rect } from "./declutter";
import { arrowLength, downwind, stationTip, type WindStation } from "./observed";
import { layoutSteps, layoutZoom, STEP_SIZE } from "./stepLayout";
import { chooseTipSide, TIP_HEIGHT, tipWidth, useTip } from "./tip";
import { useMapSettled } from "./useMapSettled";

export interface StepStop extends ChainStop {
  position: [number, number];
}

export interface LabelPoint {
  id: string;
  lon: number;
  lat: number;
  text: string;
  weight: number;
}

export interface PulsePoint {
  id: string;
  lon: number;
  lat: number;
}

const STATION_BOX = 22;
const STATION_LABEL_GAP = 12;
const OCEANS: LabelPoint[] = [
  { id: "atlantic", lon: -71.5, lat: 29, text: "Atlantic Ocean", weight: 1 },
  { id: "gulf", lon: -90, lat: 25.6, text: "Gulf of Mexico", weight: 1 },
];

const HALO = "0 0 3px var(--surface), 0 0 3px var(--surface), 0 0 2px var(--surface)";
const NO_POINTER = { pointerEvents: "none" } as const;
const SHIFT_CLASS = "transition-transform duration-200 ease-out motion-reduce:transition-none";
const shift = (dx: number, dy: number) => ({ transform: `translate(${dx}px, ${dy}px)` });

const pin = (lon: number, lat: number, dx = 0, dy = 0) => ({ "data-pin": `${lon},${lat},${dx},${dy}` });

const textWidth = (t: string, perChar: number) => Math.ceil(t.length * perChar + 8);

export const stepName = (s: Pick<StepStop, "title" | "repeated" | "assetName">) =>
  s.repeated ? `${s.title}, ${s.assetName}` : s.title;

interface Props {
  stops: StepStop[];
  activeStepKey: string | null;
  showSteps: boolean;
  /** Steps belong to the current state, so they fade while an earlier advisory is shown. */
  dimSteps: boolean;
  pulses: PulsePoint[];
  values: LabelPoint[];
  states: LabelPoint[];
  stations: WindStation[];
  showStationValues: boolean;
  onStepClick: (stop: StepStop) => void;
  onValuesZoomChange: (zoomedIn: boolean) => void;
}

/**
 * Everything drawn over the canvas is a maplibre `Marker`: maplibre moves it every frame together with the map, so
 * it cannot slide. What depends on the zoom (fan-out of step badges, which labels fit, arrow length) is decided
 * when a zoom ends and expressed as a fixed pixel offset from the symbol's own coordinates.
 */
export function Overlays({
  stops,
  activeStepKey,
  showSteps,
  dimSteps,
  pulses,
  values,
  states,
  stations,
  showStationValues,
  onStepClick,
  onValuesZoomChange,
}: Props) {
  const { current } = useMap();
  const tip = useTip();
  const settled = useMapSettled();
  const map = current?.getMap();

  const layoutAt = useMemo(() => {
    void settled;
    return map ? layoutZoom(map.getZoom()) : null;
  }, [map, settled]);
  const steps = useMemo(
    () => (layoutAt === null ? null : layoutSteps(showSteps ? stops : [], showSteps ? pulses : [], layoutAt)),
    [layoutAt, stops, pulses, showSteps],
  );

  const view = useMemo(() => {
    void settled;
    if (!map || !steps) return null;
    const project = (lon: number, lat: number) => map.project([lon, lat]);
    const zoom = map.getZoom();
    const obstacles: Rect[] = stops.flatMap((s) => {
      const offset = steps.offsets.get(s.key);
      if (!offset) return [];
      const p = project(s.position[0], s.position[1]);
      return [
        {
          x: p.x + offset[0] - STEP_SIZE / 2,
          y: p.y + offset[1] - STEP_SIZE / 2,
          w: STEP_SIZE,
          h: STEP_SIZE,
        },
      ];
    });
    const arrows = stations.map((s) => {
      const p = project(s.lon, s.lat);
      return { station: s, x: p.x, y: p.y, length: arrowLength(s.gust_mph ?? 0, zoom) };
    });
    for (const a of arrows) {
      const half = Math.max(STATION_BOX, a.length) / 2;
      obstacles.push({ x: a.x - half, y: a.y - half, w: half * 2, h: half * 2 });
    }
    const stationLabels = showStationValues
      ? placeLabels(
          arrows.flatMap((a) =>
            a.station.gust_mph === null
              ? []
              : [
                  {
                    id: a.station.station,
                    x: a.x,
                    y: a.y + Math.max(STATION_BOX, a.length) / 2 + STATION_LABEL_GAP,
                    w: textWidth(`${a.station.gust_mph} mph`, 6.8),
                    h: 16,
                    weight: a.station.gust_mph,
                  },
                ],
          ),
          null,
          obstacles,
        )
      : [];
    for (const l of stationLabels) obstacles.push({ x: l.x - l.w / 2, y: l.y - l.h / 2, w: l.w, h: l.h });
    const toCandidates = (points: LabelPoint[], perChar: number): LabelCandidate[] =>
      points.map((l) => {
        const p = project(l.lon, l.lat);
        return { id: l.id, x: p.x, y: p.y, w: textWidth(l.text, perChar), h: 16, weight: l.weight };
      });
    const showValues = zoom >= VALUE_LABEL_ZOOM;
    const frame = map.getContainer();
    const inView = { w: frame.clientWidth, h: frame.clientHeight };
    const valueSet = showValues ? placeLabels(toCandidates(values, 6.6), inView, obstacles) : [];
    const placeNames =
      zoom < VALUE_LABEL_ZOOM ? placeLabels(toCandidates([...states, ...OCEANS], 7.2), null, obstacles) : [];
    return { valueSet, placeNames, arrows, stationLabels, showValues };
  }, [map, settled, steps, stops, values, states, stations, showStationValues]);

  const showValues = view?.showValues;
  useEffect(() => {
    if (showValues !== undefined) onValuesZoomChange(showValues);
  }, [showValues, onValuesZoomChange]);

  if (!view || !map || !steps) return null;
  const text = new Map([...values, ...states, ...OCEANS].map((l) => [l.id, l.text]));
  const at = (e: { clientX: number; clientY: number }) => {
    const r = map.getContainer().getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top, width: r.width };
  };
  const stepTip = (s: StepStop) => {
    const frame = map.getContainer();
    const box = (stop: StepStop) => {
      const p = map.project(stop.position);
      const [ox, oy] = steps.offsets.get(stop.key) ?? [0, 0];
      return { x: p.x + ox - STEP_SIZE / 2, y: p.y + oy - STEP_SIZE / 2, w: STEP_SIZE, h: STEP_SIZE };
    };
    const own = box(s);
    const label = `${s.number}. ${stepName(s)}`;
    const { side, away } = chooseTipSide(
      own,
      stops.filter((o) => o.key !== s.key).map(box),
      { w: tipWidth(label), h: TIP_HEIGHT },
      { w: frame.clientWidth, h: frame.clientHeight },
    );
    tip?.set({
      text: label,
      x: own.x + STEP_SIZE / 2,
      y: own.y + STEP_SIZE / 2,
      width: frame.clientWidth,
      side,
      away,
    });
  };
  const coordsOf = new Map(
    [...values, ...states, ...OCEANS].map((l) => [l.id, [l.lon, l.lat] as [number, number]]),
  );
  return (
    <>
      {pulses.map((p) => {
        const key = steps.owners.get(p.id);
        const [dx, dy] = (key && steps.offsets.get(key)) || [0, 0];
        return (
          <Marker key={`pulse-${p.id}`} longitude={p.lon} latitude={p.lat} anchor="center" style={NO_POINTER}>
            <span style={shift(dx as number, dy as number)} className={cn("block", SHIFT_CLASS)}>
              <span
                data-testid="selected-pulse"
                {...pin(p.lon, p.lat, dx as number, dy as number)}
                aria-hidden
                className="map-pulse pointer-events-none block size-8 rounded-full bg-link"
              />
            </span>
          </Marker>
        );
      })}
      {view.placeNames.map((l) => {
        const [lon, lat] = coordsOf.get(l.id) as [number, number];
        return (
          <Marker key={l.id} longitude={lon} latitude={lat} anchor="center" style={NO_POINTER}>
            <span
              style={{ color: "var(--map-geo-label)" }}
              className={cn(
                "block text-[10.5px] font-semibold tracking-[0.08em] whitespace-nowrap uppercase",
                (l.id === "atlantic" || l.id === "gulf") && "font-medium tracking-[0.18em] italic",
              )}
            >
              {text.get(l.id)}
            </span>
          </Marker>
        );
      })}
      {view.valueSet.map((l) => {
        const [lon, lat] = coordsOf.get(l.id) as [number, number];
        return (
          <Marker key={l.id} longitude={lon} latitude={lat} anchor="center" style={NO_POINTER}>
            <span
              data-testid="map-value"
              {...pin(lon, lat)}
              style={{ textShadow: HALO }}
              className="block text-[11px] leading-4 font-semibold whitespace-nowrap text-ink tnum"
            >
              {text.get(l.id)}
            </span>
          </Marker>
        );
      })}
      {view.arrows.map((a) => (
        <Marker
          key={a.station.station}
          longitude={a.station.lon}
          latitude={a.station.lat}
          anchor="center"
          style={NO_POINTER}
        >
          <WindArrow
            station={a.station}
            length={a.length}
            onTip={(e) => tip?.set({ ...stationTip(a.station), ...at(e) })}
            onLeave={() => tip?.set(null)}
          />
        </Marker>
      ))}
      {view.stationLabels.map((l) => {
        const station = stations.find((s) => s.station === l.id) as WindStation;
        const length = view.arrows.find((a) => a.station.station === l.id)?.length ?? 0;
        return (
          <Marker
            key={`gust-${l.id}`}
            longitude={station.lon}
            latitude={station.lat}
            offset={[0, Math.round(Math.max(STATION_BOX, length) / 2 + STATION_LABEL_GAP)]}
            anchor="center"
            style={NO_POINTER}
          >
            <span
              data-testid="station-value"
              {...pin(
                station.lon,
                station.lat,
                0,
                Math.round(Math.max(STATION_BOX, length) / 2 + STATION_LABEL_GAP),
              )}
              style={{ textShadow: HALO }}
              className="block text-[11.5px] leading-4 font-bold whitespace-nowrap text-ink tnum"
            >
              {station.gust_mph} mph
            </span>
          </Marker>
        );
      })}
      {showSteps &&
        stops.map((s) => {
          const [dx, dy] = steps.offsets.get(s.key) ?? [0, 0];
          const active = s.key === activeStepKey;
          return (
            <Marker
              key={s.key}
              longitude={s.position[0]}
              latitude={s.position[1]}
              anchor="center"
              style={NO_POINTER}
            >
              <button
                type="button"
                data-testid="chain-stop"
                {...pin(s.position[0], s.position[1], dx as number, dy as number)}
                data-step={s.number}
                data-asset={s.assetId}
                aria-label={`Step ${s.number}: ${stepName(s)}`}
                aria-pressed={active}
                style={shift(dx as number, dy as number)}
                onClick={() => onStepClick(s)}
                onPointerEnter={() => stepTip(s)}
                onPointerLeave={() => tip?.set(null)}
                className={cn(
                  SHIFT_CLASS,
                  "pointer-events-auto flex size-[26px] cursor-pointer items-center justify-center rounded-full border-2 border-surface bg-primary text-[12px] leading-none font-semibold text-on-primary shadow-float tnum hover:ring-2 hover:ring-blue focus-visible:ring-2 focus-visible:ring-blue",
                  active && "ring-2 ring-blue",
                  dimSteps && "opacity-45",
                )}
              >
                {s.number}
              </button>
            </Marker>
          );
        })}
    </>
  );
}

interface ArrowProps {
  station: WindStation;
  length: number;
  onTip: (e: React.PointerEvent<HTMLButtonElement>) => void;
  onLeave: () => void;
}

const HEAD_HALF = 6;
const SHAFT_HALF = 1.7;

/** One airport: a solid arrow along the wind (pointing where it blows to), as long as the peak gust so far is strong;
 * a dot alone when no direction was reported. Faded while the station is silent. */
function WindArrow({ station, length, onTip, onLeave }: ArrowProps) {
  const size = Math.max(STATION_BOX, length) + 8;
  const half = size / 2;
  const top = half - length / 2;
  const bottom = half + length / 2;
  const neck = top + Math.min(length * 0.45, 14);
  const rotate = station.from_deg === null ? null : downwind(station.from_deg);
  const shape = [
    [half, top],
    [half + HEAD_HALF, neck],
    [half + SHAFT_HALF, neck],
    [half + SHAFT_HALF, bottom],
    [half - SHAFT_HALF, bottom],
    [half - SHAFT_HALF, neck],
    [half - HEAD_HALF, neck],
  ]
    .map(([x, y]) => `${x},${y}`)
    .join(" ");
  return (
    <button
      type="button"
      data-testid="wind-station"
      {...pin(station.lon, station.lat)}
      data-station={station.station}
      aria-label={`${station.name} airport: ${station.gust_mph === null ? "no gust yet" : `peak gust so far ${station.gust_mph} mph`}`}
      onPointerEnter={onTip}
      onPointerMove={onTip}
      onPointerLeave={onLeave}
      style={{ width: size, height: size }}
      className={cn(
        "pointer-events-auto block cursor-default rounded-full focus-visible:ring-2 focus-visible:ring-blue",
        station.silent_since_utc && "opacity-50",
      )}
    >
      <svg
        aria-hidden
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="block overflow-visible"
      >
        {rotate !== null && (
          <polygon
            points={shape}
            transform={`rotate(${rotate} ${half} ${half})`}
            fill="var(--ink)"
            stroke="var(--surface)"
            strokeWidth={1.6}
            strokeLinejoin="round"
            paintOrder="stroke"
          />
        )}
        <circle cx={half} cy={half} r={2.6} fill="var(--ink)" stroke="var(--surface)" strokeWidth={1.6} />
      </svg>
    </button>
  );
}
