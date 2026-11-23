import { KeyNumberStrip } from "@/components/sgw";
import { formatET } from "@/lib/time";
import { type Basis, shownFor } from "./format";
import type { BriefNumber } from "./types";

/** Customers out and crews working are not coloured: only a number that needs attention turns amber or red. */
function toneOf(n: BriefNumber, value: number | undefined): "warn" | "crit" | undefined {
  if (!value) return undefined;
  if (n.key === "critical_facilities") return "crit";
  if (n.key === "water_zones_advisory") return "warn";
  return undefined;
}

/** Customers out now and the forecast peak are different numbers, so they never share a label. */
function labelOf(n: BriefNumber, basis: Basis): string {
  if (n.key !== "customers_out") return n.label;
  return basis === "actual" ? "Customers out now" : "Forecast peak";
}

export function FourNumbers({ numbers, basis }: { numbers: BriefNumber[]; basis: Basis }) {
  return (
    <KeyNumberStrip
      data-testid="four-numbers"
      data-basis={basis}
      className="px-0 py-4"
      items={numbers.map((n) => {
        const shown = shownFor(n, basis, formatET);
        const value = basis === "actual" ? n.actual?.value : n.forecast?.p50;
        return {
          label: labelOf(n, basis),
          testId: `number-${n.key}`,
          value: shown ? shown.value : "—",
          tone: shown ? toneOf(n, value) : undefined,
          line: shown ? (
            <span className="block break-words text-ink-2" title={shown.source}>
              {shown.line}
            </span>
          ) : basis === "forecast" ? (
            "No forecast."
          ) : (
            "Not measured yet."
          ),
        };
      })}
    />
  );
}
