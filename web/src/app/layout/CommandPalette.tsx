import { useQuery } from "@tanstack/react-query";
import { LogOut, Moon, PanelLeft } from "lucide-react";
import { useNavigate } from "react-router";
import { useLogout } from "@/auth/useSession";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { decisionTitle } from "@/features/decisions/actionTypes";
import { api } from "@/lib/api";
import { decisionHref } from "@/lib/links";
import { useNavModules } from "./useNavModules";
import { useTheme } from "./useTheme";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onToggleSidebar: () => void;
}

/** Every typed word must appear in the item (no fuzzy letter matches that look like wrong results). */
export const wordFilter = (value: string, search: string, keywords?: string[]): number => {
  const text = `${value} ${(keywords ?? []).join(" ")}`.toLowerCase();
  const words = search.toLowerCase().split(/\s+/).filter(Boolean);
  return words.every((w) => text.includes(w)) ? 1 : 0;
};

export function CommandPalette({ open, onOpenChange, onToggleSidebar }: Props) {
  const modules = useNavModules();
  const navigate = useNavigate();
  const [, toggleTheme] = useTheme();
  const logout = useLogout();
  const proposals = useQuery({ queryKey: ["proposals"], queryFn: api.proposals, enabled: open });

  const run = (fn: () => void) => () => {
    onOpenChange(false);
    fn();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="top-[18%] translate-y-0 gap-0 p-0" aria-describedby="palette-desc">
        <DialogTitle className="sr-only">Search</DialogTitle>
        <DialogDescription id="palette-desc" className="sr-only">
          Search decisions, pages, and commands
        </DialogDescription>
        <Command label="Jump to decision or command" filter={wordFilter}>
          <CommandInput placeholder="Jump to decision or command" />
          <CommandList>
            <CommandEmpty>No results.</CommandEmpty>
            {proposals.data && proposals.data.length > 0 && (
              <CommandGroup heading="Decisions">
                {proposals.data.map((p) => (
                  <CommandItem
                    key={p.proposal_id}
                    value={`${decisionTitle(p.title)} ${p.proposal_id}`}
                    keywords={[p.title]}
                    onSelect={run(() => navigate(decisionHref(p.proposal_id)))}
                  >
                    {decisionTitle(p.title)}
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
            <CommandGroup heading="Go to">
              {modules.map((m) => (
                <CommandItem key={m.key} value={`go ${m.label}`} onSelect={run(() => navigate(m.path))}>
                  <m.icon strokeWidth={1.5} /> {m.label}
                </CommandItem>
              ))}
            </CommandGroup>
            <CommandGroup heading="Commands">
              <CommandItem value="toggle theme" onSelect={run(toggleTheme)}>
                <Moon /> Switch theme
              </CommandItem>
              <CommandItem value="toggle sidebar" onSelect={run(onToggleSidebar)}>
                <PanelLeft /> Show or hide the sidebar
              </CommandItem>
              <CommandItem
                value="sign out"
                onSelect={run(() => logout.mutate(undefined, { onSettled: () => navigate("/login") }))}
              >
                <LogOut /> Sign out
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
