import { useState } from "react";
import { type DataColumn, DataTable, InfoTip, Section, SourceLine, StatusText, Tag } from "@/components/sgw";
import type { UiSeverity } from "@/contracts/vocab.gen";
import { formatDayET, formatEtZ } from "@/lib/time";
import { EVENT_LABEL } from "./format";
import { LoadState } from "./parts";
import type { ApiToken, WebhookDelivery, WebhookSubscription } from "./types";
import { useIntegrations } from "./useAdmin";

function tokenState(t: ApiToken, now: number): { level: UiSeverity; label: string } {
  if (t.revoked_at) return { level: "critical", label: "Revoked" };
  if (Date.parse(t.expires_at) < now) return { level: "advisory", label: "Expired" };
  return { level: "normal", label: "Active" };
}

const DELIVERY: Record<WebhookDelivery["status"], { level: UiSeverity; label: string }> = {
  delivered: { level: "normal", label: "Delivered" },
  pending: { level: "elevated", label: "Retrying" },
  failed: { level: "critical", label: "Failed" },
};

const time = (iso: string | null) => (iso ? `${formatDayET(iso)}, ${formatEtZ(iso)}` : "Never");

const Mono = ({ children }: { children: React.ReactNode }) => (
  <span className="block font-mono text-[12px] text-muted">{children}</span>
);

function tokenColumns(now: number): DataColumn<ApiToken>[] {
  return [
    {
      id: "name",
      header: "Name",
      cell: (t) => (
        <>
          <span className="block text-[14px] leading-[18px] font-medium">{t.name}</span>
          <Mono>{t.token_id}</Mono>
        </>
      ),
    },
    {
      id: "scopes",
      header: (
        <span className="inline-flex items-center gap-1">
          Can read <InfoTip term="api_scope" />
        </span>
      ),
      cell: (t) => (
        <ul className="m-0 flex list-none flex-wrap gap-1 p-0">
          {t.scopes.map((s) => (
            <li key={s}>
              <Tag className="font-mono text-[11px]">{s}</Tag>
            </li>
          ))}
        </ul>
      ),
    },
    {
      id: "status",
      header: "Status",
      cell: (t) => {
        const st = tokenState(t, now);
        return <StatusText level={st.level} label={st.label} />;
      },
    },
    {
      id: "used",
      header: "Last used",
      className: "whitespace-nowrap tnum",
      cell: (t) => time(t.last_used_at),
    },
    {
      id: "expires",
      header: "Expires",
      className: "whitespace-nowrap tnum",
      cell: (t) => time(t.expires_at),
    },
  ];
}

const subColumns: DataColumn<WebhookSubscription>[] = [
  {
    id: "to",
    header: "Sent to",
    cell: (s) => (
      <>
        <span className="block font-mono text-[12px] font-medium">{s.host}</span>
        <Mono>{s.subscription_id}</Mono>
      </>
    ),
  },
  { id: "events", header: "Events", cell: (s) => s.event_types.map(EVENT_LABEL).join(", ") },
  {
    id: "status",
    header: "Status",
    cell: (s) => (
      <>
        <StatusText
          level={s.state === "active" ? "normal" : "critical"}
          label={s.state === "active" ? "Active" : "Disabled"}
        />
        {s.disabled_reason && <span className="block text-[12px] text-muted">{s.disabled_reason}</span>}
      </>
    ),
  },
  { id: "delivered", header: "Delivered", className: "tnum", cell: (s) => s.counts.delivered },
  { id: "pending", header: "Retrying", className: "tnum", cell: (s) => s.counts.pending },
  { id: "failed", header: "Failed", className: "tnum", cell: (s) => s.counts.failed },
  {
    id: "last",
    header: "Last delivery",
    className: "whitespace-nowrap tnum",
    cell: (s) => time(s.last_delivery_at),
  },
];

function deliveryColumns(subs: WebhookSubscription[]): DataColumn<WebhookDelivery>[] {
  const host = (id: string) => subs.find((s) => s.subscription_id === id)?.host ?? id;
  return [
    { id: "event", header: "Event", cell: (d) => EVENT_LABEL(d.event_type) },
    { id: "to", header: "Sent to", className: "font-mono text-[12px]", cell: (d) => host(d.subscription_id) },
    {
      id: "status",
      header: "Status",
      cell: (d) => {
        const st = DELIVERY[d.status];
        return (
          <>
            <StatusText level={st.level} label={st.label} />
            {d.last_error && <span className="block text-[12px] text-muted">{d.last_error}</span>}
          </>
        );
      },
    },
    { id: "attempts", header: "Attempts", className: "tnum", cell: (d) => d.attempts },
    {
      id: "sent",
      header: "Sent",
      className: "whitespace-nowrap tnum",
      cell: (d) => time(d.delivered_at ?? d.created_at),
    },
  ];
}

export function IntegrationsTab() {
  const data = useIntegrations();
  const [nowMs] = useState(() => Date.now());
  if (data.isPending || data.isError) return <LoadState query={data} what="integrations" />;
  const { tokens, subscriptions, deliveries } = data.data;
  return (
    <div className="flex flex-col gap-8 pb-8">
      <p className="m-0 flex items-center gap-1 px-8 text-[13px] text-muted">
        Outside systems that read decisions and receive updates. No token can sign or change anything.
        <InfoTip term="webhook" />
      </p>
      <Section title={`API tokens (${tokens.length})`} className="px-0 [&>header]:mx-8">
        {tokens.length ? (
          <div data-testid="token-table">
            <DataTable
              data={tokens}
              columns={tokenColumns(nowMs)}
              getRowId={(t) => t.token_id}
              caption="API tokens"
              rowTestId="token-row"
              edge
            />
          </div>
        ) : (
          <SourceLine className="px-8">No tokens issued.</SourceLine>
        )}
      </Section>
      <Section title={`Webhooks (${subscriptions.length})`} className="[&>header]:mx-8">
        {subscriptions.length ? (
          <div data-testid="sub-table">
            <DataTable
              data={subscriptions}
              columns={subColumns}
              getRowId={(s) => s.subscription_id}
              caption="Webhooks"
              rowTestId="sub-row"
              edge
            />
          </div>
        ) : (
          <SourceLine className="px-8">No webhooks.</SourceLine>
        )}
      </Section>
      <Section title="Latest deliveries" className="[&>header]:mx-8">
        {deliveries.length ? (
          <div data-testid="delivery-table">
            <DataTable
              data={deliveries}
              columns={deliveryColumns(subscriptions)}
              getRowId={(d) => d.delivery_id}
              caption="Latest webhook deliveries"
              rowTestId="delivery-row"
              edge
            />
          </div>
        ) : (
          <SourceLine className="px-8">Nothing has been sent yet.</SourceLine>
        )}
      </Section>
      <SourceLine className="px-8">
        Secrets and token values are never shown. Destinations are shown by host name only.
      </SourceLine>
    </div>
  );
}
