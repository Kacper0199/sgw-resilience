import { useState } from "react";
import {
  type DataColumn,
  DataTable,
  DataTableToolbar,
  InfoTip,
  SegmentedControl,
  SplitPane,
  Tag,
  TierBadge,
} from "@/components/sgw";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ACTION_LABEL, functionLabel, roleLabel } from "./format";
import { LoadState } from "./parts";
import type { ActionType, AdminUser, ApprovalRight, UserRights } from "./types";
import { useRights, useUsers } from "./useAdmin";

const ROLE_TEXT = { approver: "Signs", escalation_approver: "Signs if escalated" } as const;

function Utilities({ user }: { user: AdminUser }) {
  return (
    <span className="flex flex-wrap items-center gap-1">
      {user.domains.map((d) => (
        <Tag key={d} domain={d === "electric" ? "power" : "water"}>
          {d === "electric" ? "Power" : "Water"}
        </Tag>
      ))}
    </span>
  );
}

function RightsList({ rights }: { rights: ApprovalRight[] }) {
  if (rights.length === 0) return <p className="m-0 py-2 text-[14px] text-muted">Can't sign.</p>;
  return (
    <ul className="m-0 list-none p-0">
      {rights.map((r) => (
        <li
          key={r.action_type}
          className="flex items-center gap-3 border-b border-hair py-2.5 text-[14px] last:border-b-0"
          data-testid="right-row"
        >
          <TierBadge tier={r.tier} />
          <span className="min-w-0 flex-1">{ACTION_LABEL[r.action_type]}</span>
          <span className="text-[13px] text-muted">{ROLE_TEXT[r.role]}</span>
        </li>
      ))}
    </ul>
  );
}

function PaneFact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12px] font-semibold text-muted">{label}</dt>
      <dd className="m-0 text-[14px] font-medium">{children}</dd>
    </div>
  );
}

function PersonPane({ user, rights }: { user: AdminUser; rights: UserRights | undefined }) {
  const may = rights?.may_approve ?? [];
  return (
    <aside
      aria-label={`${user.display_name}, details`}
      data-testid="person-pane"
      className="flex min-w-0 flex-col gap-4 p-6"
    >
      <div>
        <p className="m-0 flex items-center gap-2">
          <span className="font-mono text-[12px] text-muted">{user.user_id}</span>
          <Tag>{functionLabel(user.function)}</Tag>
        </p>
        <h2 className="m-0 mt-1 text-[20px] leading-[26px] font-semibold">{user.display_name}</h2>
      </div>
      <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-3">
        <PaneFact label="Team">{functionLabel(user.function)}</PaneFact>
        <PaneFact label="Role">{user.roles.map(roleLabel).join(", ") || "None"}</PaneFact>
        <PaneFact label="Utility">
          <Utilities user={user} />
        </PaneFact>
        <PaneFact label="Regions">{user.regions.join(", ") || "None"}</PaneFact>
      </dl>
      <Tabs defaultValue="sign" key={user.user_id}>
        <TabsList aria-label="Person details">
          <TabsTrigger value="sign">Can sign</TabsTrigger>
          <TabsTrigger value="role">Role</TabsTrigger>
        </TabsList>
        <TabsContent value="sign" className="pt-2">
          <RightsList rights={may} />
        </TabsContent>
        <TabsContent value="role" className="pt-3">
          <dl className="m-0 flex flex-col gap-3">
            <PaneFact label="Roles">
              {user.roles.length ? user.roles.map(roleLabel).join(", ") : "None"}
            </PaneFact>
            <PaneFact label="Can approve alone in an emergency">
              {rights?.break_glass_eligible ? "Yes" : "No"}
            </PaneFact>
          </dl>
          <p className="m-0 mt-4 text-[13px] text-muted">
            Changing a role needs its own decision and signatures; it can't be done here.
          </p>
        </TabsContent>
      </Tabs>
    </aside>
  );
}

function ByAction({ users, rights }: { users: AdminUser[]; rights: UserRights[] }) {
  const actions = [...new Set(rights.flatMap((r) => r.may_approve.map((m) => m.action_type)))].map(
    (action) => ({
      action,
    }),
  );
  const name = (id: string) => users.find((u) => u.user_id === id)?.display_name ?? id;
  const rowsOf = (a: ActionType) =>
    rights.flatMap((r) =>
      r.may_approve.filter((m) => m.action_type === a).map((m) => ({ ...m, user_id: r.user_id })),
    );
  const columns: DataColumn<{ action: ActionType }>[] = [
    { id: "action", header: "Action", className: "font-medium", cell: (a) => ACTION_LABEL[a.action] },
    {
      id: "tier",
      header: "Approval",
      cell: (a) => {
        const first = rowsOf(a.action)[0];
        return first ? <TierBadge tier={first.tier} /> : null;
      },
    },
    {
      id: "signs",
      header: "Who signs",
      cell: (a) =>
        rowsOf(a.action)
          .filter((r) => r.role === "approver")
          .map((r) => name(r.user_id))
          .join(", ") || "Nobody",
    },
    {
      id: "escalated",
      header: "Signs if escalated",
      cell: (a) =>
        rowsOf(a.action)
          .filter((r) => r.role === "escalation_approver")
          .map((r) => name(r.user_id))
          .join(", ") || <span className="text-muted">None</span>,
    },
  ];
  return (
    <div className="min-h-0 flex-1 overflow-auto" data-testid="by-action">
      <DataTable
        data={actions}
        columns={columns}
        getRowId={(a) => a.action}
        caption="Who can sign each action"
        rowTestId="action-row"
        edge
      />
    </div>
  );
}

export function UsersTab() {
  const users = useUsers();
  const rights = useRights();
  const [view, setView] = useState<"person" | "action">("person");
  const [find, setFind] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  if (users.isPending || users.isError) return <LoadState query={users} what="users" />;
  if (rights.isPending || rights.isError) return <LoadState query={rights} what="approval rights" />;

  const rightsOf = (id: string) => rights.data.find((r) => r.user_id === id);
  const q = find.trim().toLowerCase();
  const shown = users.data.filter(
    (u) => !q || `${u.display_name} ${u.user_id} ${functionLabel(u.function)}`.toLowerCase().includes(q),
  );
  const selected = users.data.find((u) => u.user_id === picked) ?? shown[0] ?? null;

  const columns: DataColumn<AdminUser>[] = [
    {
      id: "person",
      header: "Person",
      cell: (u) => (
        <>
          <span className="block text-[14px] leading-[18px] font-medium">{u.display_name}</span>
          <span className="block font-mono text-[12px] text-muted">{u.user_id}</span>
        </>
      ),
    },
    { id: "team", header: "Team", cell: (u) => functionLabel(u.function) },
    { id: "role", header: "Role", cell: (u) => u.roles.map(roleLabel).join(", ") || "None" },
    { id: "utility", header: "Utility", cell: (u) => <Utilities user={u} /> },
    {
      id: "sign",
      header: "Can sign",
      cell: (u) => {
        const r = rightsOf(u.user_id);
        const n = r?.may_approve.length ?? 0;
        return r?.can_approve ? (
          <>
            {n} {n === 1 ? "action" : "actions"}
            {r.break_glass_eligible && (
              <span className="block text-[12px] text-muted">Can approve alone in an emergency</span>
            )}
          </>
        ) : (
          <span className="text-muted">None</span>
        );
      },
    },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <DataTableToolbar
        search={find}
        onSearch={setFind}
        searchLabel="Find a person"
        placeholder="Find a person"
      >
        <SegmentedControl
          label="Group by"
          value={view}
          onValueChange={setView}
          options={[
            { value: "person", label: "By person" },
            { value: "action", label: "By action" },
          ]}
        />
        <span className="inline-flex items-center gap-1 text-[13px] text-muted">
          Who can sign what.
          <InfoTip term="approval_rights" />
        </span>
      </DataTableToolbar>
      {view === "person" ? (
        <div className="min-h-0 flex-1 overflow-auto min-[1100px]:overflow-hidden">
          <SplitPane
            id="admin-users"
            mainMinSize={420}
            scrollMain={false}
            end={
              selected
                ? {
                    label: "Resize person details",
                    scrollRegion: "person-detail",
                    defaultSize: "36%",
                    minSize: 340,
                    maxSize: "60%",
                    content: <PersonPane user={selected} rights={rightsOf(selected.user_id)} />,
                  }
                : null
            }
          >
            <div
              className="h-full min-w-0 min-[1100px]:overflow-auto"
              data-testid="users-table"
              data-scroll-region="people-list"
            >
              <DataTable
                data={shown}
                columns={columns}
                getRowId={(u) => u.user_id}
                caption="People and what they can sign"
                selectedId={selected?.user_id ?? null}
                onSelect={(u) => setPicked(u.user_id)}
                rowTestId="user-row"
                edge
              />
            </div>
          </SplitPane>
        </div>
      ) : (
        <ByAction users={users.data} rights={rights.data} />
      )}
    </div>
  );
}
