import { Inbox, Plus, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import {
  ClockText,
  CountBadge,
  DataTable,
  DataTableToolbar,
  DomainMark,
  EmptyState,
  ErrorState,
  ExpandableRow,
  FilterChip,
  FormField,
  InfoLink,
  InfoTip,
  KeyNumberStrip,
  LoadingState,
  PageHeader,
  SegmentedControl,
  SelectField,
  Sparkline,
  StatusText,
  Tag,
  Tier,
} from "@/components/sgw";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetBody, SheetContent, SheetHeader, SheetTrigger } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { UiSeverity } from "@/contracts/vocab.gen";

const NOW = "2024-09-27T01:00:00Z";
const LEVELS: UiSeverity[] = ["critical", "severe", "elevated", "advisory", "normal", "unknown_stale"];

interface Row {
  id: string;
  title: string;
  level: UiSeverity;
  group: "mine" | "next" | "ready";
  due: string;
  domain: "power" | "water";
}
const ROWS: Row[] = [
  {
    id: "D1-0102",
    title: "Set event type to Major",
    level: "severe",
    group: "mine",
    due: "2024-09-27T01:39:00Z",
    domain: "power",
  },
  {
    id: "D3-PS17-POWER",
    title: "Restore FDR-AIK-2207 first to power PS-17",
    level: "elevated",
    group: "mine",
    due: "2024-09-27T03:29:00Z",
    domain: "water",
  },
  {
    id: "D2-0395",
    title: "Request 120 mutual-aid line workers",
    level: "advisory",
    group: "next",
    due: "2024-09-27T04:54:00Z",
    domain: "power",
  },
  {
    id: "D2-0409",
    title: "Confirm generator hookup procedure",
    level: "normal",
    group: "ready",
    due: "2024-09-27T08:00:00Z",
    domain: "water",
  },
];

const sectionTitle = "m-0 mb-3 border-b border-hair pb-2 text-[18px] leading-6 font-bold";

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8" aria-label={title}>
      <h2 className={sectionTitle}>{title}</h2>
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </section>
  );
}

/** Every primitive of the redesign in one column. Rendered once per theme on /design-check. */
export function Specimen() {
  const [view, setView] = useState("table");
  const [chip, setChip] = useState(true);
  const [selected, setSelected] = useState<string | null>("D3-PS17-POWER");
  const [find, setFind] = useState("");
  const rows = ROWS.filter((r) => r.title.toLowerCase().includes(find.toLowerCase()));
  return (
    <div className="bg-surface pb-8 text-ink">
      <PageHeader
        breadcrumb={[{ label: "SGW", to: "/" }, { label: "Respond" }, { label: "Decisions" }]}
        title="Decisions"
        count={4}
        info="decide_by"
        actions={<Button variant="secondary">Plan diff</Button>}
      />
      <KeyNumberStrip
        items={[
          { label: "Open decisions", value: 11, line: "2 severe, 5 elevated" },
          { label: "Need two signatures", value: 6 },
          { label: "Waiting on you", value: 2, tone: "warn", line: "Next due in 39 m" },
          { label: "Missed", value: 1, tone: "crit", line: "Overdue by 12 m" },
        ]}
      />
      <div className="px-8">
        <Block title="Buttons">
          <Button variant="primary">Sign as Command</Button>
          <Button variant="secondary">Send back</Button>
          <Button variant="tertiary">More in Help</Button>
          <Button variant="destructive">
            <Trash2 aria-hidden /> Approve alone…
          </Button>
          <Button variant="destructive-solid">Confirm approval</Button>
          <Button variant="primary" loading>
            Signing
          </Button>
          <Button variant="primary" disabled>
            Disabled
          </Button>
          <IconButton label="New chat" icon={<Plus aria-hidden />} />
          <IconButton label="Search" icon={<Search aria-hidden />} small />
        </Block>
        <Block title="Status text">
          {LEVELS.map((l) => (
            <StatusText key={l} level={l} />
          ))}
        </Block>
        <Block title="Tags, tiers, counts and domain marks">
          <Tag>PS-17</Tag>
          <Tag domain="power">Power</Tag>
          <Tag domain="water">Water</Tag>
          <Tier tier="T3" />
          <CountBadge count={11} />
          <CountBadge count={2} tone="warn" />
          <CountBadge count={1} tone="crit" />
          <DomainMark domain="docs" withLabel />
          <InfoTip term="decide_by" />
          <InfoLink term="decide_by" />
        </Block>
        <Block title="Chips, segmented control and select">
          <FilterChip
            label="Waiting on you"
            on={chip}
            onToggle={() => setChip((c) => !c)}
            onRemove={() => setChip(false)}
          />
          <FilterChip label="Critical path" on={false} onToggle={() => undefined} />
          <SegmentedControl
            label="View"
            value={view}
            onValueChange={setView}
            options={[
              { value: "table", label: "Table" },
              { value: "map", label: "Map" },
            ]}
          />
          <SelectField
            label="Utility"
            defaultValue="all"
            options={[
              { value: "all", label: "All" },
              { value: "power", label: "Power" },
              { value: "water", label: "Water" },
            ]}
          />
          <Sparkline
            values={[62, 62, 61.5, 60, 58, 55]}
            label="Pressure, last six readings, falling"
            tone="warn"
            limit={50}
          />
          <ClockText at="2024-09-27T03:29:00Z" now={NOW} />
        </Block>
        <Block title="Form field">
          <FormField label="Password" hint="Your password confirms this signature.">
            {(p) => <Input type="password" {...p} />}
          </FormField>
          <FormField label="Reason" error="Say why one person can approve this.">
            {(p) => <Input {...p} />}
          </FormField>
        </Block>
      </div>
      <section aria-label="Tabs" className="px-8">
        <Tabs defaultValue="deadline">
          <TabsList aria-label="Decision sections">
            {["Deadline", "Signatures", "Sequence", "History"].map((t) => (
              <TabsTrigger key={t} value={t.toLowerCase()}>
                {t}
                {t === "Signatures" && <CountBadge count="0/2" />}
              </TabsTrigger>
            ))}
          </TabsList>
          <TabsContent value="deadline">Why act now: 37 of 40 scenarios need it.</TabsContent>
        </Tabs>
      </section>
      <DataTable
        className="mt-4"
        caption="Decisions"
        data={rows}
        getRowId={(r) => r.id}
        selectedId={selected}
        onSelect={(r) => setSelected(r.id)}
        groups={[
          { id: "mine", label: "Waiting on you", tone: "warn" },
          { id: "next", label: "Next 24 hours" },
          { id: "ready", label: "Ready", folded: true, note: "folded because nothing needs attention" },
        ]}
        groupOf={(r) => r.group}
        toolbar={
          <DataTableToolbar search={find} onSearch={setFind} placeholder="Find a decision">
            <SelectField label="Owner" defaultValue="all" options={[{ value: "all", label: "All" }]} />
          </DataTableToolbar>
        }
        columns={[
          {
            id: "sev",
            header: "Severity",
            cell: (r) => <StatusText level={r.level} />,
            sort: (a, b) => LEVELS.indexOf(a.level) - LEVELS.indexOf(b.level),
          },
          {
            id: "title",
            header: "Decision",
            cell: (r) => (
              <>
                <div className="text-[14px] font-medium">{r.title}</div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[12px] text-muted">
                  <span className="font-mono">{r.id}</span>
                  <Tag domain={r.domain}>{r.domain === "power" ? "Power" : "Water"}</Tag>
                  <Tier tier="T3" />
                </div>
              </>
            ),
          },
          {
            id: "due",
            header: "Deadline",
            align: "end",
            cell: (r) => <ClockText column at={r.due} now={NOW} />,
          },
        ]}
      />
      <DataTable
        className="mt-6"
        caption="Water zones"
        data={[
          { id: "z1", name: "Cedarfall zone", note: "No backup on site" },
          { id: "z2", name: "Thomson ridge", note: "Normal" },
        ]}
        getRowId={(r) => r.id}
        defaultExpanded={(r) => r.id === "z1"}
        renderExpanded={(r) => <p className="m-0 text-[13px]">Next steps for {r.name}.</p>}
        columns={[
          { id: "name", header: "Zone", cell: (r) => r.name },
          {
            id: "note",
            header: "Backup",
            cell: (r) => <span className={r.id === "z1" ? "text-warn" : "text-muted"}>{r.note}</span>,
          },
        ]}
      />
      <table className="mt-6 w-full border-collapse text-[14px]">
        <caption className="sr-only">Standalone expandable row</caption>
        <tbody>
          <ExpandableRow
            label="Boil-water advisory"
            colSpan={2}
            detail="Probability 8.1% to 15.2% against the 10% trigger."
          >
            <td className="px-3">Boil-water advisory</td>
          </ExpandableRow>
        </tbody>
      </table>
      <div className="grid gap-6 px-8 pt-8 md:grid-cols-3">
        <EmptyState
          icon={Inbox}
          title="Nothing waits on you."
          description="New decisions appear here when they need your signature."
        />
        <LoadingState rows={3} label="Loading decisions" />
        <ErrorState thing="Decisions" onRetry={() => undefined} />
      </div>
      <div className="flex flex-wrap gap-3 px-8 pt-8">
        <Button variant="secondary" onClick={() => toast("Signed. The decision is approved.")}>
          Show toast
        </Button>
        <Button variant="secondary" onClick={() => toast.error("Could not sign. Try again.")}>
          Show error toast
        </Button>
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="secondary">Open dialog</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogTitle>Sign as Command</DialogTitle>
            <DialogDescription>Restore FDR-AIK-2207 first to power PS-17</DialogDescription>
            <FormField label="Password" hint="Your password confirms this signature.">
              {(p) => <Input type="password" {...p} />}
            </FormField>
            <DialogFooter>
              <Button variant="primary">Sign as Command</Button>
              <Button variant="secondary">Cancel</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <Sheet>
          <SheetTrigger asChild>
            <Button variant="secondary">Open sheet</Button>
          </SheetTrigger>
          <SheetContent>
            <SheetHeader title="Cedarfall zone" id="ZONE-CEDARFALL" />
            <SheetBody>Pressure 62 psi. No backup on site.</SheetBody>
          </SheetContent>
        </Sheet>
      </div>
    </div>
  );
}
