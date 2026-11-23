import { Ellipsis } from "lucide-react";
import { NavLink, useNavigate } from "react-router";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/cn";
import { type ModuleDef, TAB_BAR_KEYS } from "../modules";
import { useNavModules } from "./useNavModules";

const tab =
  "flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-1 text-[11px] font-medium text-muted no-underline hover:no-underline";

/** Below 820 px the sidebar becomes a bottom tab bar: five modules and "More". */
export function BottomTabBar({ counts }: { counts?: Partial<Record<ModuleDef["key"], number>> }) {
  const navigate = useNavigate();
  const modules = useNavModules();
  const main = TAB_BAR_KEYS.map((k) => modules.find((m) => m.key === k)).filter((m): m is ModuleDef => !!m);
  const rest = modules.filter((m) => !TAB_BAR_KEYS.includes(m.key));
  return (
    <nav
      aria-label="Main menu"
      data-testid="tab-bar"
      className="print:hidden fixed inset-x-0 bottom-0 z-30 hidden h-14 items-stretch border-t border-hair bg-surface pb-[env(safe-area-inset-bottom)] max-[819px]:flex"
    >
      {main.map((m) => (
        <NavLink
          key={m.key}
          to={m.path}
          end={m.path === "/"}
          className={({ isActive }) => cn(tab, isActive && "font-semibold text-primary")}
        >
          <span className="relative">
            <m.icon className="size-5" strokeWidth={1.5} aria-hidden />
            {counts?.[m.key] ? (
              <span className="absolute -top-1 left-3 rounded-full bg-primary px-1 text-[10px] leading-4 text-on-primary tnum">
                {counts[m.key]}
              </span>
            ) : null}
          </span>
          <span className="truncate">{m.label}</span>
        </NavLink>
      ))}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button type="button" className={tab}>
            <Ellipsis className="size-5" strokeWidth={1.5} aria-hidden />
            More
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="end">
          {rest.map((m) => (
            <DropdownMenuItem key={m.key} onSelect={() => navigate(m.path)}>
              <m.icon strokeWidth={1.5} /> {m.label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </nav>
  );
}
