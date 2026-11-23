import { X } from "lucide-react";
import { Dialog as DialogPrimitive } from "radix-ui";
import * as React from "react";
import { cn } from "@/lib/cn";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogOverlay({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      data-slot="scrim"
      className={cn("scrim sgw-fade-in fixed inset-0 z-50", className)}
      {...props}
    />
  );
}

/** Remembers what had focus when the dialog opened, before Radix moves focus inside. */
function OpenerMemo({ opener }: { opener: React.RefObject<Element | null> }) {
  React.useLayoutEffect(() => {
    opener.current = document.activeElement;
  }, [opener]);
  return null;
}

/**
 * An opaque panel over a dimmed, blurred page. Radix traps focus and closes on Esc and the scrim. Focus starts on the
 * first `[data-autofocus]` element (the safe button), else the first control, and returns to the element that
 * opened the dialog, also when no trigger is wired. `side="right"` is the 480 px sheet.
 */
export function DialogContent({
  className,
  children,
  side = "center",
  onOpenAutoFocus,
  onCloseAutoFocus,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & { side?: "center" | "right" }) {
  const opener = React.useRef<Element | null>(null);
  return (
    <DialogPrimitive.Portal>
      <DialogOverlay />
      <DialogPrimitive.Content
        data-side={side}
        onOpenAutoFocus={(e) => {
          onOpenAutoFocus?.(e);
          if (e.defaultPrevented) return;
          const target = (e.currentTarget as HTMLElement).querySelector<HTMLElement>(
            "[data-autofocus]:not(:disabled)",
          );
          if (target) {
            e.preventDefault();
            target.focus();
          }
        }}
        onCloseAutoFocus={(e) => {
          onCloseAutoFocus?.(e);
          if (e.defaultPrevented) return;
          const back = opener.current;
          if (back instanceof HTMLElement && back.isConnected && back !== document.body) {
            e.preventDefault();
            back.focus();
          }
        }}
        className={cn(
          "fixed z-50 flex flex-col gap-4 bg-surface p-6 text-ink shadow-dialog outline-none",
          side === "center" &&
            "sgw-dialog-in top-1/2 left-1/2 max-h-[calc(100dvh-32px)] w-[min(540px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-dialog",
          side === "right" &&
            "sgw-sheet-in top-0 right-0 h-full w-[min(480px,100vw)] gap-0 rounded-l-dialog p-0",
          className,
        )}
        {...props}
      >
        <OpenerMemo opener={opener} />
        {children}
        <DialogPrimitive.Close
          aria-label="Close"
          className="absolute top-3.5 right-3.5 grid size-7 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
        >
          <X className="size-4" aria-hidden />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      className={cn("m-0 pr-8 text-[20px] leading-[26px] font-semibold", className)}
      {...props}
    />
  );
}

export function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return <DialogPrimitive.Description className={cn("m-0 text-[13px] text-muted", className)} {...props} />;
}

export function DialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("flex items-center justify-end gap-2", className)} {...props} />;
}
