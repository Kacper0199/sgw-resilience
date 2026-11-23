import type { MapRef } from "@vis.gl/react-maplibre";
import { type RefObject, useEffect, useRef } from "react";
import { SELECTION_MAX_ZOOM } from "./basemap";
import type { Bounds } from "./geo";

const FIT_PADDING = 28;
const PANEL_INSET = 72;
const RIGHT_INSET = 64;
const PANEL_MIN_WIDTH = 640;
const FIT_MS = 450;
const SINGLE_POINT_ZOOM = 8.2;

export const boundsKey = (b: Bounds | null) =>
  b
    ? b
        .flat()
        .map((n) => n.toFixed(3))
        .join(",")
    : "";

interface Input {
  map: RefObject<MapRef | null>;
  ready: boolean;
  home: Bounds;
  focus: Bounds | null;
  reducedMotion: boolean;
  preview: boolean;
  /** The region frame is final (the storm's extent is in it, or no storm is drawn). */
  homeSettled: boolean;
}

/**
 * Frames the map: the focus (selected assets, steps or county) when there is one, else the region and the storm's
 * approach. A change of focus (opening a decision, clearing the selection) always re-frames. The region frame is set
 * once, as soon as it is final; later changes of it (another advisory in the history bar, a layer switched) never move
 * the camera. Returns the ref the map sets when the user pans or zooms.
 */
export function useFitView({ map, ready, home, focus, reducedMotion, preview, homeSettled }: Input) {
  const userMoved = useRef(false);
  const fitted = useRef(false);
  const lastFocus = useRef("");
  const homeFramed = useRef(false);
  const latest = useRef({ home, focus, preview, homeSettled });
  latest.current = { home, focus, preview, homeSettled };
  const homeKey = boundsKey(home);
  const focusKey = boundsKey(focus);

  useEffect(() => {
    const instance = map.current;
    if (!ready || !instance) return;
    const focusChanged = focusKey !== lastFocus.current;
    const homeOnly = !focusChanged && homeKey !== "";
    if (homeOnly && (userMoved.current || homeFramed.current)) return;
    lastFocus.current = focusKey;
    const duration = reducedMotion || !fitted.current ? 0 : FIT_MS;
    fitted.current = true;
    userMoved.current = false;
    const { home: frame, focus: target, preview: small, homeSettled: final } = latest.current;
    if (final && !target) homeFramed.current = true;
    const { clientWidth, clientHeight } = instance.getContainer();
    const pad = Math.max(8, Math.min(FIT_PADDING, Math.floor(Math.min(clientWidth, clientHeight) / 4)));
    const wide = !small && clientWidth >= PANEL_MIN_WIDTH;
    const padding = {
      top: pad,
      bottom: pad,
      left: wide ? PANEL_INSET : pad,
      right: wide ? RIGHT_INSET : pad,
    };
    if (!target) {
      instance.fitBounds(frame, { padding, duration });
    } else if (target[0][0] === target[1][0] && target[0][1] === target[1][1]) {
      instance.easeTo({ center: target[0], zoom: SINGLE_POINT_ZOOM, padding, duration });
    } else {
      instance.fitBounds(target, {
        padding: { ...padding, top: pad + 40, bottom: pad + 40 },
        maxZoom: SELECTION_MAX_ZOOM,
        duration,
      });
    }
  }, [map, ready, focusKey, homeKey, reducedMotion]);

  return userMoved;
}
