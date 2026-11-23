import { Popover as PopoverPrimitive } from "radix-ui";
import type * as React from "react";
import { cn } from "@/lib/cn";

export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export const PopoverAnchor = PopoverPrimitive.Anchor;

/** An outlined arrow that sits on the bubble border; the base is covered so it reads as a notch. */
export function PopoverArrow({ className, ...props }: React.ComponentProps<typeof PopoverPrimitive.Arrow>) {
  return (
    <PopoverPrimitive.Arrow asChild {...props}>
      <svg
        width="14"
        height="7"
        viewBox="0 0 14 7"
        className={cn("block overflow-visible", className)}
        aria-hidden
      >
        <path d="M0 0 L7 6.5 L14 0 Z" className="fill-surface" />
        <path d="M0 0 L7 6.5 L14 0" fill="none" className="stroke-hair-strong" strokeWidth="1" />
        <rect x="0.8" y="-1.2" width="12.4" height="2" className="fill-surface" />
      </svg>
    </PopoverPrimitive.Arrow>
  );
}

export function PopoverContent({
  className,
  align = "start",
  sideOffset = 6,
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        align={align}
        sideOffset={sideOffset}
        collisionPadding={8}
        className={cn(
          "z-50 w-72 rounded-lg bg-surface p-3 text-[13px] text-ink shadow-pop outline-none",
          "data-[state=open]:animate-in data-[state=open]:fade-in-0 duration-120",
          className,
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  );
}
