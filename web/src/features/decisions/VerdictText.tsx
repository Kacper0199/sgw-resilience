import { InfoTip } from "@/components/sgw";
import type { GlossaryKey } from "@/content/glossary";
import type { NoRegretVerdict } from "@/contracts/vocab.gen";
import { cn } from "@/lib/cn";
import { usePhase } from "@/lib/PhaseProvider";
import { timingText } from "./ui";

const TIP: Record<NoRegretVerdict, GlossaryKey | null> = {
  act_now: "no_regret_act_now",
  decide_now: "no_regret_act_now",
  wait_for_next_advisory: "no_regret_wait",
  "n/a": null,
};

/** The Timing word: Act now, Before next advisory or Can wait; a dash where there is no advice. Plain text; no
 * colour, no fill. */
export function VerdictText({ verdict, withTip = false }: { verdict: NoRegretVerdict; withTip?: boolean }) {
  const phase = usePhase();
  const tip = TIP[verdict];
  const text = timingText(verdict, phase);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-[13px] leading-[18px]",
        verdict === "act_now" || verdict === "decide_now" ? "font-medium text-ink" : "text-muted",
      )}
    >
      {text ?? "—"}
      {text && withTip && tip && <InfoTip term={tip} />}
    </span>
  );
}
