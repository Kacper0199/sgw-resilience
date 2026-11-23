import { AlertCircle } from "lucide-react";
import type * as React from "react";
import { useId } from "react";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/cn";

interface FormFieldProps {
  label: string;
  hint?: string;
  /** Replaces the hint: red text with an alert icon. */
  error?: string;
  className?: string;
  children: (props: {
    id: string;
    "aria-describedby": string;
    "aria-invalid": boolean | undefined;
  }) => React.ReactNode;
}

/** Label above, hint below, the error replaces the hint. */
export function FormField({ label, hint, error, className, children }: FormFieldProps) {
  const id = useId();
  const noteId = `${id}-note`;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <Label htmlFor={id}>{label}</Label>
      {children({ id, "aria-describedby": noteId, "aria-invalid": error ? true : undefined })}
      {error ? (
        <p id={noteId} role="alert" className="m-0 flex items-center gap-1.5 text-[12px] text-crit">
          <AlertCircle className="size-3.5 shrink-0" aria-hidden />
          {error}
        </p>
      ) : (
        <p id={noteId} className="m-0 text-[12px] text-muted">
          {hint}
        </p>
      )}
    </div>
  );
}
