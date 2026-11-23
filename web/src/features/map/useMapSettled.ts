import { useMap } from "@vis.gl/react-maplibre";
import { useEffect, useState } from "react";

/**
 * Bumps when the view has come to rest after a zoom or a resize, never during a move. Overlays that depend on the
 * zoom (which labels fit, how large an arrow is) recompute here, while everything else stays pinned to its
 * coordinates by maplibre on every frame.
 */
export function useMapSettled(): number {
  const { current } = useMap();
  const [settled, setSettled] = useState(0);
  useEffect(() => {
    const map = current?.getMap();
    if (!map) return;
    const bump = () => setSettled((n) => n + 1);
    map.on("zoomend", bump);
    map.on("resize", bump);
    bump();
    return () => {
      map.off("zoomend", bump);
      map.off("resize", bump);
    };
  }, [current]);
  return settled;
}
