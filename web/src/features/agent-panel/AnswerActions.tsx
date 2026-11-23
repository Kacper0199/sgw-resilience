import { useMutation } from "@tanstack/react-query";
import {
  BookOpenText,
  Check,
  Copy,
  Ellipsis,
  ListChecks,
  RotateCcw,
  ThumbsDown,
  ThumbsUp,
  Workflow,
} from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { IconButton } from "@/components/ui/icon-button";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { agentApi } from "./api";

interface Props {
  threadId: string;
  runId: string;
  copyText: string;
  sourceCount: number;
  hasTrace: boolean;
  canAskAgain: boolean;
  /** The assistant could not write an answer: only "Try again" (and details) make sense, not copy, ratings or sources. */
  unavailable?: boolean;
  onTrace: () => void;
  /** Set for the people who may see how the answer was made: the menu then offers that instead of the Activity page. */
  onHowMade?: () => void;
  onAskAgain: () => void;
  onShowSources: () => void;
  /** The question was Polish: the source count reads in Polish. */
  polish?: boolean;
}

const PL_SOURCES = ["źródło", "źródła", "źródeł"] as const;
const plSources = (n: number): string =>
  PL_SOURCES[n === 1 ? 0 : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 1 : 2];

type Rating = "up" | "down";

/** The icon row under an answer: copy, helpful, not helpful, ask again, "N sources", more. */
export function AnswerActions({
  threadId,
  runId,
  copyText,
  sourceCount,
  hasTrace,
  canAskAgain,
  unavailable = false,
  onTrace,
  onHowMade,
  onAskAgain,
  onShowSources,
  polish = false,
}: Props) {
  const [copied, setCopied] = useState(false);
  const [rating, setRating] = useState<Rating | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const send = useMutation({
    mutationFn: (r: Rating) => agentApi.feedback(threadId, runId, { rating: r }),
    onSuccess: (_d, r) => {
      setRating(r);
      setNote("Thanks for the feedback.");
    },
    onError: (err) => {
      setNote(
        err instanceof ApiError && (err.status === 404 || err.status === 405)
          ? "Feedback isn't available yet."
          : "Feedback couldn't be sent.",
      );
    },
  });

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(copyText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setNote("Your browser blocked copying.");
    }
  };

  if (unavailable) {
    return (
      <div className="mt-1 flex flex-wrap items-center gap-2" data-testid="answer-actions-unavailable">
        <Button variant="secondary" size="sm" disabled={!canAskAgain} onClick={onAskAgain}>
          <RotateCcw aria-hidden />
          Try again
        </Button>
      </div>
    );
  }

  return (
    <div className="-ml-2 mt-1 flex flex-wrap items-center gap-0.5">
      <IconButton
        small
        label="Copy answer"
        onClick={copy}
        icon={copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      />
      {(["up", "down"] as const).map((r) => (
        <IconButton
          key={r}
          small
          label={r === "up" ? "Helpful" : "Not helpful"}
          aria-pressed={rating === r}
          disabled={send.isPending}
          onClick={() => send.mutate(r)}
          className={cn(rating === r && "bg-blue-soft text-blue-ink")}
          icon={r === "up" ? <ThumbsUp aria-hidden /> : <ThumbsDown aria-hidden />}
        />
      ))}
      <IconButton
        small
        label="Ask again"
        disabled={!canAskAgain}
        onClick={onAskAgain}
        icon={<RotateCcw aria-hidden />}
      />
      {sourceCount > 0 && (
        <Button variant="tertiary" size="sm" onClick={onShowSources} className="px-2">
          <BookOpenText aria-hidden />
          {sourceCount} {polish ? plSources(sourceCount) : sourceCount === 1 ? "source" : "sources"}
        </Button>
      )}
      {hasTrace && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <IconButton small label="More" icon={<Ellipsis aria-hidden />} />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {onHowMade ? (
              <DropdownMenuItem onSelect={onHowMade}>
                <Workflow aria-hidden />
                How this answer was made
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem onSelect={onTrace}>
                <ListChecks aria-hidden />
                Step details in Activity
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      <span role="status" className="ml-2 text-[12px] text-muted">
        {note}
      </span>
    </div>
  );
}
