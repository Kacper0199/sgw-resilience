import type * as React from "react";
import { cn } from "@/lib/cn";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "./dialog";

export const Sheet = Dialog;
export const SheetTrigger = DialogTrigger;
export const SheetClose = DialogClose;

/** The 480 px side sheet: header with title and id, a body that scrolls on its own. */
export function SheetContent({ className, children, ...props }: React.ComponentProps<typeof DialogContent>) {
  return (
    <DialogContent side="right" className={className} {...props}>
      {children}
    </DialogContent>
  );
}

export function SheetHeader({
  title,
  id,
  description,
  className,
}: {
  title: React.ReactNode;
  id?: string;
  description?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("shrink-0 border-b border-hair px-6 pt-5 pb-4 pr-14", className)}>
      <DialogTitle className="text-[18px] leading-6">{title}</DialogTitle>
      {id && <p className="m-0 mt-0.5 font-mono text-[12px] text-muted">{id}</p>}
      {description ? <DialogDescription className="mt-1">{description}</DialogDescription> : null}
    </header>
  );
}

export function SheetBody({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("min-h-0 flex-1 overflow-y-auto px-6 py-5", className)} {...props} />;
}
