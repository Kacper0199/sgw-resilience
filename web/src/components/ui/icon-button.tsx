import type * as React from "react";
import { cn } from "@/lib/cn";
import { Button, type ButtonProps } from "./button";
import { Tooltip, TooltipContent, TooltipTrigger } from "./tooltip";

interface IconButtonProps extends Omit<ButtonProps, "size" | "children" | "aria-label"> {
  /** Required: it is the accessible name and the tooltip text. */
  label: string;
  icon: React.ReactNode;
  small?: boolean;
  /** Where the tooltip opens; `bottom` for icons in a header. */
  tooltipSide?: "top" | "bottom" | "left" | "right";
}

/** The only way to draw an icon-only button: the tooltip and the accessible name cannot be left out. */
export function IconButton({
  label,
  icon,
  small = false,
  tooltipSide,
  variant = "ghost",
  className,
  ...props
}: IconButtonProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          aria-label={label}
          variant={variant}
          size={small ? "icon-sm" : "icon"}
          className={cn("text-muted hover:text-ink", className)}
          {...props}
        >
          {icon}
        </Button>
      </TooltipTrigger>
      <TooltipContent side={tooltipSide}>{label}</TooltipContent>
    </Tooltip>
  );
}
