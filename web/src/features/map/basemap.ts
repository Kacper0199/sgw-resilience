const origin = () => new URL(import.meta.env.BASE_URL, window.location.origin).href;

export const geoUrl = (name: string) => new URL(`geo/${name}`, origin()).href;

export const MAX_BOUNDS: [number, number, number, number] = [-98, 16, -62, 46];
export const MIN_ZOOM = 3;
export const MAX_ZOOM = 10;
export const VALUE_LABEL_ZOOM = 6.3;
export const STATE_LABEL_ZOOM = 6.3;
export const SELECTION_MAX_ZOOM = 9.5;
