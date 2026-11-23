import { InfoTip } from "@/components/sgw";
import type { Envelope } from "@/lib/api";
import { formatEtZ } from "@/lib/time";
import { PaneSection } from "./PaneSection";
import { PolicyChips } from "./policyChips";

export const humanizeKey = (key: string): string => {
  const text = key.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};

/** For a T3 decision with an approved envelope: a short chip next to the title. */
export function EnvelopeChip({ envelope }: { envelope: Envelope | null | undefined }) {
  if (!envelope) return null;
  return (
    <span
      data-testid="envelope-chip"
      className="inline-flex items-center gap-1 rounded-sm bg-subtle px-1.5 py-0.5 text-label font-medium text-ink"
    >
      Pre-approved limits, valid until {formatEtZ(envelope.valid_until_utc)}
      <InfoTip term="envelope" />
    </span>
  );
}

export function EnvelopeCard({ envelope }: { envelope: Envelope }) {
  const rows = Object.entries(envelope.bounds);
  return (
    <PaneSection title="Pre-approved limits" info="envelope">
      <div className="flex flex-col gap-2 text-[13px]">
        <p className="m-0 text-muted tnum">
          Changes inside the pre-approved limits need no new signature until{" "}
          {formatEtZ(envelope.valid_until_utc)}.
        </p>
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="text-left text-label text-muted">
              <th className="py-1 font-medium">Item</th>
              <th className="py-1 text-end font-medium">Lowest</th>
              <th className="py-1 text-end font-medium">Highest</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([key, b]) => (
              <tr key={key} className="border-t border-hair">
                <td className="py-1.5">{humanizeKey(key)}</td>
                <td className="py-1.5 text-end tnum">{b.min}</td>
                <td className="py-1.5 text-end tnum">{b.max}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <PolicyChips keys={["policy_envelope_pct"]} />
      </div>
    </PaneSection>
  );
}
