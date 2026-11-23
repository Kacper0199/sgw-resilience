export const count = (n: number): string => Math.round(n).toLocaleString("en-US");
export const percent = (ratio: number): string => `${Math.round(ratio * 100)}%`;
export const signed = (n: number): string => `${n >= 0 ? "+" : "−"}${count(Math.abs(n))}`;
export const millions = (n: number): string => `${(n / 1e6).toFixed(1)} M`;
export const ofForty = (ppm: number, members: number): string =>
  `${Math.round((ppm / 1e6) * members)} of ${members}`;

const STATES: Record<string, string> = { "13": "GA", "45": "SC" };
export const countyLabel = (name: string, fips: string): string => {
  const state = STATES[fips.slice(0, 2)];
  return state ? `${name}, ${state}` : name;
};
