import { ChevronDown, LogOut, Users } from "lucide-react";
import { useNavigate } from "react-router";
import { FUNCTION_LABEL } from "@/auth/personas";
import { useLogout, useMe } from "@/auth/useSession";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { useReducedTransparency } from "./useTransparency";

const initials = (name: string) =>
  name
    .split(/[\s,()]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");

export function PersonaMenu() {
  const { data: me } = useMe();
  const logout = useLogout();
  const navigate = useNavigate();
  const [reduced, setReduced] = useReducedTransparency();
  if (!me) return null;
  const [role = me.display_name, unit] = me.display_name.split(/,\s*/, 2);
  const team = unit ?? FUNCTION_LABEL[me.function];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex h-[34px] items-center gap-2 rounded-md px-1.5 text-left hover:bg-topbar-hover"
        >
          <span
            aria-hidden
            className="inline-grid size-6 place-items-center rounded-full bg-topbar-field text-[11px] font-medium"
          >
            {initials(me.display_name)}
          </span>
          <span className="sr-only">Signed in as </span>
          <span className="leading-tight max-[819px]:sr-only" title={me.display_name}>
            <span className="block max-w-44 truncate text-[12px] font-medium">{role}</span>
            <span className="block max-w-44 truncate text-[11px] text-topbar-muted">{team}</span>
          </span>
          <ChevronDown className="size-3.5 text-topbar-muted" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>{me.user_id}</DropdownMenuLabel>
        {me.demo_mode && (
          <DropdownMenuItem onSelect={() => navigate("/login", { state: { switching: true } })}>
            <Users /> Switch user
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={(e) => {
            e.preventDefault();
            setReduced(!reduced);
          }}
          role="menuitemcheckbox"
          aria-checked={reduced}
        >
          <span className="flex-1">Reduce transparency</span>
          <Switch checked={reduced} aria-hidden tabIndex={-1} className="pointer-events-none" />
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() =>
            logout.mutate(undefined, { onSettled: () => navigate("/login", { replace: true }) })
          }
        >
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
