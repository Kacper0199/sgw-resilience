import { CornerDownRight } from "lucide-react";
import { CHIP } from "./AnswerLinks";

interface Props {
  questions: readonly string[];
  busy: boolean;
  onAsk: (question: string) => void;
  label?: string;
}

/** Questions to try next, as chips: one click asks it in the same conversation. */
export function QuestionChips({ questions, busy, onAsk, label = "Questions to ask next" }: Props) {
  if (questions.length === 0) return null;
  return (
    <ul aria-label={label} className="m-0 flex list-none flex-wrap gap-2 p-0" data-testid="question-chips">
      {questions.map((q) => (
        <li key={q} className="min-w-0 max-w-full">
          <button type="button" disabled={busy} onClick={() => onAsk(q)} className={`${CHIP} text-ink`}>
            <CornerDownRight aria-hidden className="size-3.5 shrink-0 text-muted" />
            <span className="truncate">{q}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
