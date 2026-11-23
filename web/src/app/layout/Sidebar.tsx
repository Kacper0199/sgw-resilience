import { ChevronDown, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useState } from "react";
import { NavLink, useLocation } from "react-router";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { GROUP_LABEL, type ModuleDef, type NavGroup } from "../modules";
import { useNavModules } from "./useNavModules";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  counts?: Partial<Record<ModuleDef["key"], number>>;
}

const GROUPS_KEY = "sgw.navgroups";
const GROUPS = ["respond", "inform", "user"] as const satisfies readonly NavGroup[];

const readClosed = (): Partial<Record<NavGroup, boolean>> => {
  try {
    return JSON.parse(localStorage.getItem(GROUPS_KEY) ?? "{}");
  } catch {
    return {};
  }
};

function Entry({ def, collapsed, count }: { def: ModuleDef; collapsed: boolean; count?: number }) {
  const Icon = def.icon;
  const inCase = useLocation().pathname.startsWith("/decisions/") && def.key === "decisions";
  const link = (
    <NavLink
      to={def.path}
      end={def.path === "/"}
      aria-label={collapsed ? def.label : undefined}
      className={({ isActive }) =>
        cn(
          "relative flex h-9 items-center gap-3 rounded-md px-2.5 text-[14px] whitespace-nowrap text-ink no-underline transition-colors duration-120 hover:bg-surface-2 hover:no-underline",
          (isActive || inCase) &&
            "bg-selected font-semibold before:absolute before:inset-y-1.5 before:-left-2 before:w-[3px] before:rounded-r-sm before:bg-primary",
          collapsed && "justify-center px-0",
        )
      }
    >
      <Icon className="size-[18px] shrink-0 text-muted" strokeWidth={1.5} aria-hidden />
      {!collapsed && <span className="truncate">{def.label}</span>}
      {!collapsed && count ? <span className="ml-auto text-[12px] text-muted tnum">{count}</span> : null}
    </NavLink>
  );
  if (!collapsed) return link;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">{def.label}</TooltipContent>
    </Tooltip>
  );
}

/** White sidebar: collapsible groups, or a 56 px rail with tooltips. Hidden below 820 px (the tab bar takes over). */
export function Sidebar({ collapsed, onToggle, counts }: SidebarProps) {
  const [closed, setClosed] = useState(readClosed);
  const modules = useNavModules();
  const toggleGroup = (g: NavGroup) =>
    setClosed((c) => {
      const next = { ...c, [g]: !c[g] };
      try {
        localStorage.setItem(GROUPS_KEY, JSON.stringify(next));
      } catch {
        /* storage unavailable */
      }
      return next;
    });
  return (
    <aside
      data-testid="sidebar"
      className={cn(
        "flex h-full w-full flex-col overflow-x-hidden overflow-y-auto bg-surface p-2 max-[819px]:hidden",
      )}
    >
      <div className={cn("mb-1 flex h-8 items-center", collapsed ? "justify-center" : "justify-end")}>
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          className="print:hidden grid size-7 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
        >
          {collapsed ? (
            <PanelLeftOpen className="size-4" aria-hidden />
          ) : (
            <PanelLeftClose className="size-4" aria-hidden />
          )}
        </button>
      </div>
      <nav aria-label="Main menu" className="flex flex-1 flex-col gap-0.5">
        {GROUPS.map((g) => {
          const open = collapsed || !closed[g];
          const id = `navgroup-${g}`;
          return (
            <div key={g} className={cn("flex flex-col gap-0.5", g === "user" && "mt-auto")}>
              {!collapsed && (
                <button
                  type="button"
                  aria-expanded={open}
                  aria-controls={id}
                  onClick={() => toggleGroup(g)}
                  className="flex h-8 items-center gap-1 rounded-md px-2.5 pt-2 text-[12px] font-semibold text-muted hover:text-ink"
                >
                  {GROUP_LABEL[g]}
                  <ChevronDown
                    className={cn("size-3.5 transition-transform duration-[160ms]", !open && "-rotate-90")}
                    aria-hidden
                  />
                </button>
              )}
              {collapsed && g !== "respond" && <div className="mx-2 my-1.5 h-px bg-hair" />}
              <div id={id} hidden={!open} className="flex flex-col gap-0.5">
                {modules
                  .filter((m) => m.group === g)
                  .map((m) => (
                    <Entry key={m.key} def={m} collapsed={collapsed} count={counts?.[m.key]} />
                  ))}
              </div>
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
