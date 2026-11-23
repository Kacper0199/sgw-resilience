import { Ellipsis } from "lucide-react";
import { useState } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { IconButton } from "@/components/ui/icon-button";
import { crewName } from "@/lib/names";
import { type DialogMode, DispatchDialog } from "./DispatchDialog";
import { type CrewAction, MENU_LABEL, useDispatch } from "./dispatch";
import type { CrewItem } from "./types";

const SIGN_OFF: CrewAction[] = ["sign", "reject", "withdraw"];

/** One row menu with only what this person may do now; no menu at all when there is nothing. */
export function CrewMenu({ crew }: { crew: CrewItem }) {
  const actions = crew.actions ?? [];
  const dispatch = useDispatch(crew.crew_id);
  const [dialog, setDialog] = useState<DialogMode | null>(null);
  if (actions.length === 0) return null;
  const signOff = actions.filter((a) => SIGN_OFF.includes(a));
  const rest = actions.filter((a) => !SIGN_OFF.includes(a));
  const item = (a: CrewAction) => (
    <DropdownMenuItem
      key={a}
      data-testid={`crew-action-${a}`}
      className={a === "reject" ? "text-crit" : undefined}
      onSelect={() => {
        if (a === "assign") setDialog("assign");
        else if (a === "block") setDialog("block");
        else if (a === "reject") setDialog("reject");
        else dispatch.mutate({ kind: a as Exclude<CrewAction, "assign" | "block" | "reject"> });
      }}
    >
      {MENU_LABEL[a]}
    </DropdownMenuItem>
  );
  return (
    <>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <IconButton
            small
            label={`Actions for ${crewName(crew.crew_id)}`}
            icon={<Ellipsis aria-hidden />}
            disabled={dispatch.isPending}
            data-testid="crew-menu"
          />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {signOff.map(item)}
          {signOff.length > 0 && rest.length > 0 && <DropdownMenuSeparator />}
          {rest.map(item)}
        </DropdownMenuContent>
      </DropdownMenu>
      <DispatchDialog crewId={crew.crew_id} mode={dialog} onClose={() => setDialog(null)} />
    </>
  );
}
