import { Tooltip as TooltipPrimitive } from "radix-ui";
import type * as React from "react";
import { cn } from "@/lib/cn";

export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export function TooltipContent({
  className,
  sideOffset = 6,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        sideOffset={sideOffset}
        className={cn(
          "z-50 rounded-md bg-toast px-2 py-1 text-xs font-medium text-on-toast shadow-pop",
          "data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0 duration-120",
          className,
        )}
        {...props}
      />
    </TooltipPrimitive.Portal>
  );
}
