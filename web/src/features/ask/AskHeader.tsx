import { Menu, PanelLeft, SquarePen } from "lucide-react";
import { InfoLink } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { cn } from "@/lib/cn";

interface Props {
  historyOpen: boolean;
  onToggleHistory: () => void;
  onNewChat: () => void;
  /** A conversation is open: only then is there something to leave. */
  hasConversation: boolean;
  /** Null when the chat has no sources: the toggle is absent. */
  sources: { open: boolean; count: number; onToggle: () => void } | null;
}

/** History toggle on the left, a quiet New conversation action next to the title once a conversation exists, Sources toggle on the right. */
export function AskHeader({ historyOpen, onToggleHistory, onNewChat, hasConversation, sources }: Props) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 px-6 max-[819px]:px-4">
      <IconButton
        tooltipSide="bottom"
        label={historyOpen ? "Hide chat history" : "Show chat history"}
        aria-pressed={historyOpen}
        aria-controls={historyOpen ? "history-panel" : undefined}
        onClick={onToggleHistory}
        className={cn("max-[819px]:hidden", historyOpen && "bg-blue-soft text-blue-ink hover:text-blue-ink")}
        icon={<PanelLeft aria-hidden />}
      />
      <h1 className="m-0 ml-1 text-[20px] leading-7 font-bold tracking-[-0.01em]">Ask AI</h1>
      <InfoLink term="copilot" />
      {hasConversation && (
        <Button variant="ghost" size="sm" onClick={onNewChat} className="ml-1 text-muted hover:text-ink">
          <SquarePen aria-hidden className="size-3.5" />
          New conversation
        </Button>
      )}
      <span className="flex-1" />
      {sources && (
        <span className="relative">
          <IconButton
            tooltipSide="bottom"
            label={sources.open ? "Hide sources" : "Sources"}
            aria-pressed={sources.open}
            aria-controls={sources.open ? "sources-panel" : undefined}
            onClick={sources.onToggle}
            className={cn(sources.open && "bg-blue-soft text-blue-ink hover:text-blue-ink")}
            icon={<Menu aria-hidden />}
          />
          <span
            aria-hidden
            className="pointer-events-none absolute -top-1.5 -right-1.5 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-primary px-1 text-[11px] leading-none font-semibold text-on-primary tnum"
          >
            {sources.count}
          </span>
        </span>
      )}
    </header>
  );
}
