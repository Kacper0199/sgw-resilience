import type { MapRef } from "@vis.gl/react-maplibre";
import { type RefObject, useEffect, useState } from "react";
import { NO_DATA_PATTERN } from "./MapLayers";

const SIZE = 8;
const RATIO = 2;

function drawHatch(line: string): ImageData | null {
  const canvas = document.createElement("canvas");
  canvas.width = SIZE * RATIO;
  canvas.height = SIZE * RATIO;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.scale(RATIO, RATIO);
  ctx.strokeStyle = line;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (const shift of [-SIZE, 0, SIZE]) {
    ctx.moveTo(shift, SIZE);
    ctx.lineTo(shift + SIZE, 0);
  }
  ctx.stroke();
  return ctx.getImageData(0, 0, SIZE * RATIO, SIZE * RATIO);
}

/** Registers the diagonal hatch that marks counties the outage feed has no report for, in the theme's colour. */
export function useHatchPattern(map: RefObject<MapRef | null>, ready: boolean, line: string): boolean {
  const [registered, setRegistered] = useState(false);
  useEffect(() => {
    const instance = map.current?.getMap();
    if (!ready || !instance || !line) return;
    const image = drawHatch(line);
    if (!image) return;
    if (instance.hasImage(NO_DATA_PATTERN)) instance.removeImage(NO_DATA_PATTERN);
    instance.addImage(NO_DATA_PATTERN, image, { pixelRatio: RATIO });
    setRegistered(true);
  }, [map, ready, line]);
  return registered;
}
