import { ChevronDown, Users } from "lucide-react";
import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { DEMO_OTHERS, DEMO_PEOPLE, type DemoPerson } from "./demoPeople";
import { PERSONAS } from "./personas";

const focusables = (pop: HTMLElement | null) =>
  Array.from(pop?.querySelectorAll<HTMLElement>('[role="option"], [data-more]') ?? []);

const titleOf = (id: string) => PERSONAS.find((p) => p.user_id === id)?.title ?? id;

interface Props {
  value: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (userId: string) => void;
}

function Option({ person, selected, onPick }: { person: DemoPerson; selected: boolean; onPick: () => void }) {
  return (
    <button
      type="button"
      role="option"
      tabIndex={-1}
      aria-selected={selected}
      data-user-id={person.user_id}
      onClick={onPick}
      className={cn(
        "flex w-full items-start gap-3 rounded-md p-2.5 text-start hover:bg-surface-2 focus-visible:bg-surface-2",
        selected && "bg-selected hover:bg-selected",
      )}
    >
      <span
        aria-hidden
        className="inline-flex size-8 shrink-0 items-center justify-center rounded-full border border-blue-line bg-blue-soft text-[11px] font-semibold tracking-[0.02em] text-blue-ink"
      >
        {person.initials}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-2 text-[14px] leading-[1.3] font-semibold text-ink">
          <span>{titleOf(person.user_id)}</span>
          <span className="font-mono text-[11.5px] font-normal text-muted">{person.user_id}</span>
        </span>
        <span className="mt-0.5 block text-[12.5px] leading-[1.35] text-muted">{person.line}</span>
      </span>
    </button>
  );
}

/** The "Demo people" popover on the User ID field: a listbox of seven people and a folded "Other accounts" listbox. */
export function PersonChooser({ value, open, onOpenChange, onPick }: Props) {
  const [more, setMore] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const popId = useId();
  const othersId = useId();
  const id = value.trim();

  useEffect(() => {
    const pop = popRef.current;
    if (!open || !pop) return;
    (pop.querySelector<HTMLElement>('[role="option"][aria-selected="true"]') ?? focusables(pop)[0])?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const root = rootRef.current;
    const away = (e: PointerEvent) => {
      if (!root?.contains(e.target as Node)) onOpenChange(false);
    };
    const focusLeft = (e: FocusEvent) => {
      if (e.relatedTarget && !root?.contains(e.relatedTarget as Node)) onOpenChange(false);
    };
    document.addEventListener("pointerdown", away);
    root?.addEventListener("focusout", focusLeft);
    return () => {
      document.removeEventListener("pointerdown", away);
      root?.removeEventListener("focusout", focusLeft);
    };
  }, [open, onOpenChange]);

  const close = (refocus: boolean) => {
    onOpenChange(false);
    if (refocus) triggerRef.current?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const list = focusables(popRef.current);
    const at = list.indexOf(document.activeElement as HTMLElement);
    const go = (target: HTMLElement | undefined) => {
      e.preventDefault();
      target?.focus();
    };
    if (e.key === "ArrowDown") go(list[at + 1] ?? list[0]);
    else if (e.key === "ArrowUp") go(list[at - 1] ?? list[list.length - 1]);
    else if (e.key === "Home") go(list[0]);
    else if (e.key === "End") go(list[list.length - 1]);
    else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close(true);
    }
  };

  const toggleMore = () => {
    const next = !more;
    setMore(next);
    if (next)
      requestAnimationFrame(() =>
        popRef.current?.querySelector('[data-user-id="ops_dm_02"]')?.scrollIntoView({ block: "nearest" }),
      );
  };

  const pick = (userId: string) => {
    onPick(userId);
    onOpenChange(false);
  };

  return (
    <div ref={rootRef} className="contents">
      <div className="absolute inset-y-0 end-0 flex items-center">
        <button
          ref={triggerRef}
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={popId}
          onClick={() => (open ? close(true) : onOpenChange(true))}
          className="inline-flex h-11 items-center gap-1.5 rounded-e-lg px-3 text-[13px] font-semibold text-blue-ink hover:bg-blue-soft"
        >
          <Users className="size-4" aria-hidden />
          Demo people
          <ChevronDown className="size-4" aria-hidden />
        </button>
      </div>
      {open && <div className="scrim lg-scrim" aria-hidden onClick={() => close(true)} />}
      {/* biome-ignore lint/a11y/noStaticElementInteractions: the key handler moves focus between the options inside it */}
      <div id={popId} ref={popRef} hidden={!open} className="lg-pop" onKeyDown={onKeyDown}>
        <div role="listbox" aria-label="Demo people">
          {DEMO_PEOPLE.map((p) => (
            <Option key={p.user_id} person={p} selected={id === p.user_id} onPick={() => pick(p.user_id)} />
          ))}
        </div>
        <button
          type="button"
          data-more
          aria-expanded={more}
          aria-controls={othersId}
          onClick={toggleMore}
          className="mt-1 flex w-full items-center gap-2 border-t border-hair p-2.5 text-[13px] font-semibold text-blue-ink hover:bg-blue-soft"
        >
          <ChevronDown
            className={cn("size-4 transition-transform duration-160", more && "rotate-180")}
            aria-hidden
          />
          Other accounts ({DEMO_OTHERS.length})
        </button>
        <div id={othersId} role="listbox" aria-label="Other accounts" hidden={!more}>
          {DEMO_OTHERS.map((p) => (
            <Option key={p.user_id} person={p} selected={id === p.user_id} onPick={() => pick(p.user_id)} />
          ))}
        </div>
      </div>
    </div>
  );
}

/** The one place the demo password is written out for people; shown only when the server says it is true. */
export function DemoPasswordNote({ id, password }: { id: string; password: string }) {
  return (
    <p id={id} className="m-0 mt-2.5 text-center text-xs leading-[1.33] text-muted">
      Demo password is {password}. Demo only.
    </p>
  );
}
