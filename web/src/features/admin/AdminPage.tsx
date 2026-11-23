import { Info, ShieldAlert } from "lucide-react";
import { parseAsString, parseAsStringLiteral, useQueryState } from "nuqs";
import { useMe } from "@/auth/useSession";
import { EmptyState, KeyNumberStrip, LoadingState, PageHeader, Tag } from "@/components/sgw";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useScenario } from "@/sse/useScenarioNow";
import { AiConfigTab } from "./AiConfigTab";
import { AuditTab } from "./AuditTab";
import { isAdmin } from "./format";
import { IntegrationsTab } from "./IntegrationsTab";
import { MetricsTab } from "./MetricsTab";
import { PoliciesTab } from "./PoliciesTab";
import { UsersTab } from "./UsersTab";
import { useRights, useUsers } from "./useAdmin";

const TABS = ["users", "policies", "integrations", "audit", "ai", "metrics"] as const;
type Tab = (typeof TABS)[number];
const options = { history: "replace" } as const;

function AdminStrip() {
  const users = useUsers().data;
  const rights = useRights().data;
  const count = (n: number | undefined) => n ?? "—";
  return (
    <KeyNumberStrip
      className="shrink-0"
      items={[
        { label: "People", value: count(users?.length), line: "With a sign-in" },
        {
          label: "Can sign",
          value: count(rights?.filter((r) => r.can_approve).length),
          line: users ? `of ${users.length}` : undefined,
        },
        {
          label: "Can approve alone",
          value: count(rights?.filter((r) => r.break_glass_eligible).length),
          line: "In an emergency",
        },
        {
          label: "Teams",
          value: count(users && new Set(users.map((u) => u.function)).size),
          line: "Each person is on one team",
        },
      ]}
    />
  );
}

export default function AdminPage() {
  const me = useMe();
  const scenario = useScenario();
  const [tab, setTab] = useQueryState(
    "tab",
    parseAsStringLiteral(TABS).withDefault("users").withOptions(options),
  );
  const [key] = useQueryState("key", parseAsString.withOptions(options));

  if (me.isPending) return <LoadingState rows={5} label="Loading…" className="p-8" />;
  if (!isAdmin(me.data))
    return (
      <div className="flex flex-col">
        <PageHeader title="Admin" />
        <EmptyState icon={ShieldAlert} title="Admin is for the platform team. Ask them for changes." />
      </div>
    );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader title="Admin" info="page_admin" actions={<Tag>Read-only</Tag>} />
      {scenario.data?.mode === "EXERCISE" && (
        <p
          role="note"
          data-testid="exercise-banner"
          className="m-0 mx-8 mb-2 flex items-center gap-2 border-y border-hair py-2 text-[13px] text-ink-2"
        >
          <Info className="size-4 shrink-0 text-muted" aria-hidden />
          Exercise with synthetic data, not for operational use.
        </p>
      )}
      <AdminStrip />
      <Tabs value={tab} onValueChange={(v) => void setTab(v as Tab)} className="flex min-h-0 flex-1 flex-col">
        <TabsList aria-label="Admin sections" className="shrink-0 px-8">
          <TabsTrigger value="users">Users and roles</TabsTrigger>
          <TabsTrigger value="policies">Policies</TabsTrigger>
          <TabsTrigger value="integrations">Integrations</TabsTrigger>
          <TabsTrigger value="audit">Audit log</TabsTrigger>
          <TabsTrigger value="ai">AI settings</TabsTrigger>
          <TabsTrigger value="metrics">System metrics</TabsTrigger>
        </TabsList>
        <TabsContent value="users" className="flex min-h-0 flex-1 flex-col pt-0">
          <UsersTab />
        </TabsContent>
        <TabsContent
          value="policies"
          data-scroll-region="admin-tab"
          className="min-h-0 flex-1 overflow-auto pt-0"
        >
          <PoliciesTab selectedKey={key} />
        </TabsContent>
        <TabsContent
          value="integrations"
          data-scroll-region="admin-tab"
          className="min-h-0 flex-1 overflow-auto pt-4"
        >
          <IntegrationsTab />
        </TabsContent>
        <TabsContent
          value="audit"
          data-scroll-region="admin-tab"
          className="min-h-0 flex-1 overflow-auto pt-4"
        >
          <AuditTab />
        </TabsContent>
        <TabsContent value="ai" data-scroll-region="admin-tab" className="min-h-0 flex-1 overflow-auto pt-4">
          <AiConfigTab />
        </TabsContent>
        <TabsContent
          value="metrics"
          data-scroll-region="admin-tab"
          className="min-h-0 flex-1 overflow-auto pt-4"
        >
          <MetricsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
