import { NuqsAdapter } from "nuqs/adapters/react-router/v8";
import { useEffect, useRef, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import type { PanelImperativeHandle } from "react-resizable-panels";
import { Outlet } from "react-router";
import { SplitPane, useMediaQuery } from "@/components/sgw";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useWaitingOnMe } from "@/features/decisions/useQueue";
import { useUnreadCount } from "@/features/notifications/useNotifications";
import { overlayOpen } from "@/lib/overlay";
import { useWorld } from "@/lib/world";
import { BottomTabBar } from "./BottomTabBar";
import { CommandPalette } from "./CommandPalette";
import { Sidebar } from "./Sidebar";
import { SkipLink } from "./SkipLink";
import { TopBand } from "./TopBand";

const KEY = "sgw.sidebar";
const RAIL = 56;
const NAV_MIN = 200;
const NAV_MAX = 360;
const NAV_DEFAULT = 232;

export const initialCollapsed = (): boolean => {
  const saved = localStorage.getItem(KEY);
  if (saved) return saved === "collapsed";
  return false;
};

/** Dark navy top band, white sidebar (a bottom tab bar below 820 px), one scrolling content area. */
export function Shell() {
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [palette, setPalette] = useState(false);
  const waiting = useWaitingOnMe();
  const world = useWorld();
  const unread = useUnreadCount();
  const counts = { decisions: waiting, notifications: unread };

  const wide = useMediaQuery("(min-width: 820px)");
  const nav = useRef<PanelImperativeHandle>(null);
  const openWidth = useRef(NAV_DEFAULT);
  const collapsedBefore = useRef(collapsed);
  useEffect(() => {
    if (collapsedBefore.current === collapsed) return;
    collapsedBefore.current = collapsed;
    if (!collapsed) nav.current?.resize(openWidth.current);
  }, [collapsed]);

  const toggleSidebar = () => {
    setCollapsed((c) => {
      localStorage.setItem(KEY, c ? "open" : "collapsed");
      return !c;
    });
  };

  useHotkeys("mod+k", () => setPalette((o) => !o), {
    preventDefault: true,
    enableOnFormTags: true,
    enabled: (e) => palette || !overlayOpen(e),
  });

  return (
    <TooltipProvider delayDuration={150}>
      <SkipLink />
      <div className="relative flex h-full flex-col overflow-hidden">
        <TopBand onOpenPalette={() => setPalette(true)} />
        <div className="min-h-0 flex-1">
          <SplitPane
            id="shell"
            stackBelow={0}
            mainMinSize={480}
            saveUserSizesOnly
            start={
              wide
                ? {
                    label: "Resize navigation",
                    content: <Sidebar collapsed={collapsed} onToggle={toggleSidebar} counts={counts} />,
                    defaultSize: NAV_DEFAULT,
                    minSize: collapsed ? RAIL : NAV_MIN,
                    maxSize: collapsed ? RAIL : NAV_MAX,
                    disabled: collapsed,
                    panelRef: nav,
                    scroll: false,
                    onResize: (px) => {
                      if (!collapsed && px >= NAV_MIN) openWidth.current = px;
                    },
                  }
                : null
            }
            scrollMain={false}
          >
            <main
              id="main"
              tabIndex={-1}
              className="h-full min-w-0 overflow-auto bg-surface outline-none max-[819px]:pb-14"
            >
              <NuqsAdapter>
                <Outlet key={world} />
              </NuqsAdapter>
            </main>
          </SplitPane>
        </div>
        <BottomTabBar counts={counts} />
      </div>
      <CommandPalette open={palette} onOpenChange={setPalette} onToggleSidebar={toggleSidebar} />
    </TooltipProvider>
  );
}
