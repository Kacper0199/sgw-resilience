import { ArrowUp, Lock, Square } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { InfoTip } from "@/components/sgw";
import { IconButton } from "@/components/ui/icon-button";

interface Props {
  running: boolean;
  disabled?: boolean;
  placeholder: string;
  scope?: string;
  autoFocus?: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}

const MAX_CHARS = 2000;

/** The rounded composer: the question, a scope chip and the navy send circle, with the disclaimer under it. */
export function Composer({
  running,
  disabled = false,
  placeholder,
  scope,
  autoFocus = false,
  onSend,
  onStop,
}: Props) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  const id = useId();
  const clean = text.trim();
  const canSend = clean.length > 0 && !running && !disabled;

  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);

  const submit = () => {
    if (!canSend) return;
    onSend(clean);
    setText("");
    if (ref.current) ref.current.style.height = "";
  };

  return (
    <div className="w-full">
      <div className="rounded-composer bg-surface px-4 pt-3 pb-2.5 shadow-composer">
        <label htmlFor={id} className="sr-only">
          Ask about the storm response
        </label>
        <textarea
          id={id}
          ref={ref}
          value={text}
          rows={1}
          maxLength={MAX_CHARS}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(e) => {
            setText(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = `${Math.min(e.target.scrollHeight, 140)}px`;
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          className="block max-h-[140px] min-h-[26px] w-full resize-none border-0 bg-transparent p-0 text-[15px] leading-[26px] text-ink outline-none placeholder:text-muted"
        />
        <div className="mt-2 flex items-center gap-2">
          {scope && (
            <span className="inline-flex h-6 items-center gap-1 rounded-sm border border-hair-strong px-1.5 text-[12px] text-ink-2">
              <Lock aria-hidden className="size-3" />
              {scope}
            </span>
          )}
          <span className="flex-1" />
          {running ? (
            <IconButton
              label="Stop response"
              variant="primary"
              onClick={onStop}
              className="rounded-full text-on-primary hover:text-on-primary"
              icon={<Square aria-hidden className="size-3.5 fill-current" />}
            />
          ) : (
            <IconButton
              label="Send"
              variant="primary"
              onClick={submit}
              disabled={!canSend}
              className="rounded-full text-on-primary hover:text-on-primary"
              icon={<ArrowUp aria-hidden className="size-[18px]" />}
            />
          )}
        </div>
      </div>
      <p className="m-0 mt-2 flex flex-wrap items-center justify-center gap-x-1 text-[12px] text-muted">
        AI can make mistakes. Check the sources before you act.
        <span className="inline-flex items-center">
          Read-only
          <InfoTip term="read_only" />
        </span>
      </p>
    </div>
  );
}
