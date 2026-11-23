import { parseAsString, parseAsStringLiteral, useQueryState } from "nuqs";
import { useEffect, useMemo, useState } from "react";
import { SplitPane } from "@/components/sgw";
import { Sheet, SheetBody, SheetContent, SheetHeader } from "@/components/ui/sheet";
import { parseAnswer } from "../agent-panel/parseAnswer";
import type { RunView } from "../agent-panel/types";
import { AskHeader } from "./AskHeader";
import { ChatPane } from "./ChatPane";
import { HistoryPanel } from "./HistoryPanel";
import { RunsPane } from "./RunsPane";
import { SourcesList, SourcesPanel } from "./SourcesPanel";
import { sourceCount, sourcesOf } from "./sources";
import { TraceSheet } from "./trace";
import { useAsk } from "./useAsk";
import { useWide } from "./useWide";

const VIEWS = ["chat", "runs"] as const;

export default function AskPage() {
  const ask = useAsk();
  const wide = useWide();
  const [view, setView] = useQueryState("tab", parseAsStringLiteral(VIEWS).withDefault("chat"));
  const [runParam, setRunParam] = useQueryState("run", parseAsString);
  const [picked, setPicked] = useState<{ runId: string; n: number | null } | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [sourcesPref, setSourcesPref] = useState<Record<string, boolean>>({});

  const lastWithAnswer = [...ask.turns].reverse().find((t) => t.answerText);
  const newestId = lastWithAnswer?.runId;
  useEffect(() => {
    if (newestId) setPicked(null);
  }, [newestId]);
  const activeTurn = ask.turns.find((t) => t.runId === picked?.runId) ?? lastWithAnswer ?? null;
  const parsed = useMemo(
    () => (activeTurn?.answerText ? parseAnswer(activeTurn.answerText, activeTurn.run?.answer?.path) : null),
    [activeTurn],
  );
  const sources = useMemo(() => {
    const set = sourcesOf(parsed, activeTurn?.run ?? null, activeTurn?.references ?? []);
    return activeTurn && activeTurn.citations.length > 0 ? { ...set, docs: activeTurn.citations } : set;
  }, [parsed, activeTurn]);
  const count = sourceCount(sources);

  const prefKey = ask.threadId ?? "new";
  const sourcesOpen = wide && view === "chat" && count > 0 && (sourcesPref[prefKey] ?? true);
  const setSources = (open: boolean) => {
    if (wide) setSourcesPref((p) => ({ ...p, [prefKey]: open }));
    else setSheetOpen(open);
  };
  const showSources = () => setSources(true);

  const selectSource = (runId: string, n: number) => {
    setPicked({ runId, n });
    showSources();
  };
  const showSourcesOf = (runId: string) => {
    setPicked({ runId, n: null });
    showSources();
  };
  const openTrace = (runId: string) => {
    void setRunParam(runId);
    void setView("runs");
  };
  const sendAsk = (q: string) => {
    void setView("chat");
    void ask.ask(q);
  };
  const runAgain = (run: RunView) => {
    void setView("chat");
    void ask.ask(run.question ?? "", run.threadId);
  };
  const openChat = (threadId: string) => {
    void ask.openThread(threadId);
    void setView("chat");
  };
  const newChat = () => {
    void ask.openThread(null);
    void setView("chat");
  };

  return (
    <div className="h-full min-h-[480px]">
      <SplitPane
        id="ask"
        stackBelow={0}
        mainMinSize={420}
        scrollMain={false}
        start={
          historyOpen && wide
            ? {
                label: "Resize chat history",
                defaultSize: 264,
                minSize: 200,
                maxSize: 400,
                scroll: false,
                content: (
                  <HistoryPanel
                    threads={ask.threads}
                    currentId={ask.threadId}
                    activityCount={ask.runs.length}
                    onOpen={openChat}
                    onActivity={() => void setView("runs")}
                  />
                ),
              }
            : null
        }
        end={
          sourcesOpen
            ? {
                label: "Resize sources",
                defaultSize: 340,
                minSize: 260,
                maxSize: 560,
                scroll: false,
                content: (
                  <SourcesPanel
                    sources={sources}
                    activeN={picked?.n ?? null}
                    readAt={activeTurn?.run?.scenarioTime ?? null}
                    onClose={() => setSources(false)}
                  />
                ),
              }
            : null
        }
      >
        <div className="flex h-full min-w-0 flex-col">
          <AskHeader
            historyOpen={historyOpen}
            onToggleHistory={() => setHistoryOpen((o) => !o)}
            onNewChat={newChat}
            hasConversation={ask.turns.length > 0}
            sources={
              view === "chat" && count > 0
                ? {
                    open: wide ? sourcesOpen : sheetOpen,
                    count,
                    onToggle: () => setSources(!(wide ? sourcesOpen : sheetOpen)),
                  }
                : null
            }
          />
          {view === "chat" ? (
            <ChatPane
              turns={ask.turns}
              threadId={ask.threadId}
              loading={ask.messagesLoading && ask.turns.length === 0}
              running={Boolean(ask.active)}
              error={ask.error}
              activeRunId={activeTurn?.runId ?? null}
              activeN={picked?.n ?? null}
              onAsk={sendAsk}
              onAskAgain={sendAsk}
              onStop={() => ask.active && ask.stop(ask.active)}
              onSelectSource={selectSource}
              onShowSources={showSourcesOf}
              onTrace={openTrace}
            />
          ) : (
            <RunsPane
              runs={ask.runs}
              selectedId={runParam}
              onSelect={(id) => void setRunParam(id)}
              onRunAgain={runAgain}
              onOpenConversation={(run) => openChat(run.threadId)}
              onBack={() => void setView("chat")}
            />
          )}
        </div>
      </SplitPane>
      <TraceSheet />
      {!wide && (
        <Sheet open={sheetOpen && count > 0} onOpenChange={setSheetOpen}>
          <SheetContent aria-describedby={undefined}>
            <SheetHeader title="Sources" />
            <SheetBody className="px-0 py-0">
              <SourcesList
                sources={sources}
                activeN={picked?.n ?? null}
                readAt={activeTurn?.run?.scenarioTime ?? null}
              />
            </SheetBody>
          </SheetContent>
        </Sheet>
      )}
    </div>
  );
}
