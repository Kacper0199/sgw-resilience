import { formatDayET, formatET } from "./time";

const ADVISORY_WORDS: [RegExp, string][] = [
  [/\bN(?:-\d+)? to N\+1\b/g, "previous to latest advisory"],
  [/\badvisory N\+1\b/gi, "the latest advisory"],
  [/\badvisory N(?![+-]\d)\b/gi, "the previous advisory"],
  [/\badvisory N-\d+\b/gi, "an earlier advisory"],
  [/\badvisory N\+[2-9]\b/gi, "the next advisory"],
];

/** Server and mock sentences name advisories "N" and "N+1"; people read "previous" and "latest". */
export function plainAdvisory(text: string): string {
  let out = text;
  for (const [pattern, words] of ADVISORY_WORDS) {
    const source = out;
    out = source.replace(pattern, (match, offset: number) => {
      const atStart = offset === 0 || /[.!?]\s$/.test(source.slice(Math.max(0, offset - 2), offset));
      const capital = atStart && /^A/.test(match);
      return capital ? words.charAt(0).toUpperCase() + words.slice(1) : words;
    });
  }
  return out;
}

/** An advisory by its issue time, for example "Sep 26 11:00 ET". */
export function advisoryTime(issuedUtc: string): string {
  return `${formatDayET(issuedUtc)} ${formatET(issuedUtc)}`;
}
