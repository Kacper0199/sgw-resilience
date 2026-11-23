import { type ClockShift, describeShift } from "./clockShifts";

const SUFFIX = ["th", "st", "nd", "rd"];

export function ordinal(n: number): string {
  const v = n % 100;
  return `${n}${SUFFIX[(v - 20) % 10] ?? SUFFIX[v] ?? SUFFIX[0]}`;
}

export interface Reorderable {
  id: string;
  caseId: string;
  title: string;
}

/**
 * A sentence for a screen-reader user when a decision moved up the queue because its decide-by moved:
 * "Restore FDR-AIK-2207 first to power PS-17 moved to 2nd, decide-by earlier by 1 h 16 m".
 */
export function reorderNotice(
  before: string[],
  after: Reorderable[],
  shifts: Record<string, ClockShift>,
): string {
  if (before.length === 0) return "";
  const notes: string[] = [];
  after.forEach((row, index) => {
    const was = before.indexOf(row.id);
    const shift = shifts[row.caseId];
    if (was === -1 || was === index || !shift) return;
    const how = describeShift(shift).text.split(", was ")[0]?.toLowerCase() ?? "";
    notes.push(`${row.title} moved to position ${index + 1}; deadline ${how}`);
  });
  return notes.join(". ");
}
