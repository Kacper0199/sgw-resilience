import { BellRing } from "lucide-react";
import { Link } from "react-router";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { decisionTitle } from "@/features/decisions/actionTypes";
import { cn } from "@/lib/cn";
import { formatDayET, formatET } from "@/lib/time";
import { type Notification, useMarkRead, useNotifications } from "./useNotifications";

const when = (iso: string) => `${formatDayET(iso)}, ${formatET(iso)}`;

function Row({ item, onOpen }: { item: Notification; onOpen: (id: string) => void }) {
  return (
    <li className="border-b border-hair">
      <Link
        to={item.href}
        onClick={() => !item.read && onOpen(item.notification_id)}
        data-testid="notification"
        data-read={item.read ? "true" : "false"}
        className="flex items-start gap-3 px-8 py-3 text-ink no-underline transition-colors duration-120 hover:bg-surface-2 hover:no-underline"
      >
        <span
          aria-hidden
          className={cn("mt-[7px] size-2 shrink-0 rounded-full", item.read ? "bg-transparent" : "bg-primary")}
        />
        <span className="min-w-0 flex-1">
          <span className={cn("block text-[14px] leading-snug", !item.read && "font-semibold")}>
            {item.title}
            {!item.read && <span className="sr-only"> (unread)</span>}
          </span>
          {item.detail && (
            <span className="mt-0.5 block truncate text-[13px] text-muted">{decisionTitle(item.detail)}</span>
          )}
        </span>
        <span className="shrink-0 pt-0.5 text-[12px] text-muted tnum">{when(item.at)}</span>
      </Link>
    </li>
  );
}

export default function NotificationsPage() {
  const feed = useNotifications();
  const mark = useMarkRead();
  const unread = feed.data?.unread ?? 0;
  return (
    <div className="flex min-h-full flex-col">
      <PageHeader
        breadcrumb={[{ label: "SGW", to: "/" }, { label: "Your account" }]}
        title="Notifications"
        count={unread || undefined}
        actions={
          unread > 0 ? (
            <Button variant="secondary" disabled={mark.isPending} onClick={() => mark.mutate({ all: true })}>
              Mark all read
            </Button>
          ) : null
        }
      />
      {feed.isPending ? (
        <LoadingState rows={4} label="Loading notifications" className="px-5" />
      ) : feed.error ? (
        <ErrorState thing="Notifications" onRetry={() => void feed.refetch()} className="py-16" />
      ) : feed.data.items.length === 0 ? (
        <EmptyState icon={BellRing} title="Nothing for you right now." className="py-16" />
      ) : (
        <ul aria-label="Notifications" className="m-0 list-none border-t border-hair p-0">
          {feed.data.items.map((item) => (
            <Row
              key={item.notification_id}
              item={item}
              onOpen={(id) => mark.mutate({ ids: [id], all: false })}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
