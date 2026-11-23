import { CircleCheck } from "lucide-react";
import { lazy, Suspense } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/cn";
import { FUNCTION_LABEL, PERSONAS } from "./personas";

const PersonChooser = lazy(() => import("./PersonChooser").then((m) => ({ default: m.PersonChooser })));

interface Props {
  value: string;
  onChange: (value: string) => void;
  demo: boolean;
  invalid: boolean;
  describedBy?: string;
  chooserOpen: boolean;
  onChooserOpenChange: (open: boolean) => void;
  onPick: (userId: string) => void;
}

const triggerSpace = "inline-flex h-11 items-center px-3 text-[13px] font-semibold text-muted";

/** User ID with, in demo mode only, the "Demo people" chooser and a line saying which function the typed account signs as. */
export function UserIdField({ value, onChange, demo, invalid, describedBy, ...chooser }: Props) {
  const person = demo ? PERSONAS.find((p) => p.user_id === value.trim()) : undefined;
  return (
    <div>
      <Label htmlFor="user-id" className="mb-1.5 block text-[13px] leading-[1.35] font-semibold">
        User ID
      </Label>
      <div className="relative">
        <Input
          id="user-id"
          name="username"
          autoComplete="username"
          autoCapitalize="off"
          spellCheck={false}
          placeholder={demo ? "e.g. ic_01" : undefined}
          value={value}
          aria-invalid={invalid || undefined}
          aria-describedby={[person && "signs-as", describedBy].filter(Boolean).join(" ") || undefined}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (demo && e.key === "ArrowDown") {
              e.preventDefault();
              chooser.onChooserOpenChange(true);
            }
          }}
          className={cn(
            "h-11 border-(--login-line) px-3 text-[15px] hover:border-muted focus-visible:border-blue aria-invalid:shadow-[inset_0_0_0_1px_var(--crit)]",
            demo && "pe-[150px]",
          )}
          required
        />
        {demo && (
          <Suspense
            fallback={
              <span className="absolute inset-y-0 end-0 flex items-center">
                <span className={triggerSpace}>Demo people</span>
              </span>
            }
          >
            <PersonChooser
              value={value}
              open={chooser.chooserOpen}
              onOpenChange={chooser.onChooserOpenChange}
              onPick={chooser.onPick}
            />
          </Suspense>
        )}
      </div>
      <div aria-live="polite">
        {person && (
          <p id="signs-as" className="m-0 mt-2 flex items-center gap-2 text-[13px] leading-[1.35] text-ink-2">
            <CircleCheck className="size-4 shrink-0 text-ok" aria-hidden />
            <span>
              <b className="font-semibold text-ink">{person.title}</b>, signs as{" "}
              {FUNCTION_LABEL[person.function]}
            </span>
          </p>
        )}
      </div>
    </div>
  );
}
