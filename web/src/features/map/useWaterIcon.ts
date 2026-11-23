import type { MapRef } from "@vis.gl/react-maplibre";
import { type RefObject, useEffect, useState } from "react";
import { WATER_ICON } from "./MapLayers";

const SIZE = 18;
const RATIO = 2;
const SIDE = 11;

function drawSquare(fill: string, edge: string): ImageData | null {
  const canvas = document.createElement("canvas");
  canvas.width = SIZE * RATIO;
  canvas.height = SIZE * RATIO;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.scale(RATIO, RATIO);
  const at = (SIZE - SIDE) / 2;
  ctx.beginPath();
  ctx.roundRect(at, at, SIDE, SIDE, 2.5);
  ctx.lineWidth = 2.4;
  ctx.strokeStyle = edge;
  ctx.stroke();
  ctx.fillStyle = fill;
  ctx.fill();
  return ctx.getImageData(0, 0, SIZE * RATIO, SIZE * RATIO);
}

/** Registers the water-asset symbol (a rounded square, so it cannot be read as a storm-track point) in the theme's colours. */
export function useWaterIcon(
  map: RefObject<MapRef | null>,
  ready: boolean,
  fill: string,
  edge: string,
): boolean {
  const [registered, setRegistered] = useState(false);
  useEffect(() => {
    const instance = map.current?.getMap();
    if (!ready || !instance || !fill) return;
    const image = drawSquare(fill, edge);
    if (!image) return;
    if (instance.hasImage(WATER_ICON)) instance.removeImage(WATER_ICON);
    instance.addImage(WATER_ICON, image, { pixelRatio: RATIO });
    setRegistered(true);
  }, [map, ready, fill, edge]);
  return registered;
}
