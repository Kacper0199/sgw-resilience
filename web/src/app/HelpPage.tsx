import { Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router";
import { DataTableToolbar, EmptyState, PageHeader } from "@/components/sgw";
import { DATA_SOURCES } from "@/content/dataSources";
import { GLOSSARY } from "@/content/glossary";

const ENTRIES = Object.entries(GLOSSARY)
  .map(([key, e]) => ({ key, term: e.term, text: e.text }))
  .sort((a, b) => a.term.localeCompare(b.term, "en", { numeric: true }));

const letter = (term: string) => (/^[a-z]/i.test(term) ? term.charAt(0).toUpperCase() : "#");

export default function HelpPage() {
  const { hash } = useLocation();
  const [find, setFind] = useState("");
  const q = find.trim().toLowerCase();
  const shown = useMemo(
    () => ENTRIES.filter((e) => !q || `${e.term} ${e.text}`.toLowerCase().includes(q)),
    [q],
  );
  const groups = useMemo(() => {
    const map = new Map<string, typeof ENTRIES>();
    for (const e of shown) map.set(letter(e.term), [...(map.get(letter(e.term)) ?? []), e]);
    return [...map.entries()];
  }, [shown]);
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [hash]);
  return (
    <div className="flex min-h-full flex-col">
      <PageHeader
        breadcrumb={[{ label: "SGW", to: "/" }, { label: "Your account" }, { label: "Help" }]}
        title="Help"
        count={ENTRIES.length}
      />
      <p className="m-0 px-8 pb-1 text-[14px] text-ink-2">Definitions of the terms used here.</p>
      <DataTableToolbar
        search={find}
        onSearch={setFind}
        searchLabel="Find a term"
        placeholder="Find a term"
      />
      <section id="data-sources" aria-labelledby="data-sources-title" className="scroll-mt-6 pb-4">
        <h2
          id="data-sources-title"
          className="m-0 border-b border-hair bg-surface-2 px-8 py-2 text-[13px] font-semibold text-ink-2 max-[819px]:px-4"
        >
          Data sources
        </h2>
        <dl className="m-0" data-testid="help-data-sources">
          {DATA_SOURCES.map((d) => (
            <div
              key={d.key}
              className="grid gap-x-8 border-b border-hair px-8 py-3 max-[819px]:px-4 min-[820px]:grid-cols-[240px_minmax(0,1fr)]"
            >
              <dt className="text-[14px] font-semibold">{d.what}</dt>
              <dd className="m-0 max-w-[80ch] text-[14px] leading-5 text-ink-2">
                {d.real ? "Real" : "Synthetic"}, from {d.source} ({d.licence})
              </dd>
            </div>
          ))}
        </dl>
        <p className="m-0 px-8 pt-2 text-[12px] text-muted max-[819px]:px-4">
          Full list with files and links: data/ATTRIBUTION.md in the repository.
        </p>
      </section>
      {shown.length === 0 ? (
        <EmptyState icon={Search} title="No terms match." description="Try a shorter word." />
      ) : (
        <div className="pb-16" data-testid="glossary">
          {groups.map(([l, entries]) => (
            <section key={l} aria-labelledby={`letter-${l}`} className="mt-4 first:mt-0">
              <h2
                id={`letter-${l}`}
                className="m-0 border-b border-hair bg-surface-2 px-8 py-2 text-[13px] font-semibold text-ink-2 max-[819px]:px-4"
              >
                {l}
              </h2>
              <dl className="m-0">
                {entries.map((e) => (
                  <div
                    key={e.key}
                    id={e.key}
                    className="grid scroll-mt-6 gap-x-8 border-b border-hair px-8 py-3 max-[819px]:px-4 min-[820px]:grid-cols-[240px_minmax(0,1fr)]"
                  >
                    <dt className="text-[14px] font-semibold">{e.term}</dt>
                    <dd className="m-0 max-w-[80ch] text-[14px] leading-5 text-ink-2">{e.text}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
