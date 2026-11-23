import { FUNCTION_LABEL } from "@/auth/personas";
import { Section } from "@/components/sgw";
import type { FunctionLine } from "./types";

export function FunctionLines({ lines }: { lines: FunctionLine[] }) {
  return (
    <Section title="By team">
      <dl className="m-0">
        {lines.map((l) => (
          <div
            key={l.function}
            className="grid gap-x-6 gap-y-0.5 border-b border-hair py-3 min-[600px]:grid-cols-[160px_minmax(0,1fr)]"
            data-testid="function-line"
          >
            <dt className="text-[13px] font-semibold">{FUNCTION_LABEL[l.function]}</dt>
            <dd className="m-0 min-w-0 text-[15px] leading-6">{l.sentence}</dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}
