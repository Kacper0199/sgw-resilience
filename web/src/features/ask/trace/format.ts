export const ms = (value: number | null): string => {
  if (value === null) return "–";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(value < 90_000 ? 1 : 0)} s`;
};

export const count = (n: number): string => n.toLocaleString("en-US");

export const compact = (n: number): string =>
  n < 1000 ? String(n) : `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;

export const cost = (micros: number): string => (micros <= 0 ? "–" : `$${(micros / 1_000_000).toFixed(3)}`);
