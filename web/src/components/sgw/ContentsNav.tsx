import { cn } from "@/lib/cn";

interface ContentsItem {
  id: string;
  label: string;
}

/**
 * The sticky "On this page" list beside a report (Briefing, After-action): the section in view has the navy bar.
 * It sits in the 200 px column right of the 820 px reading column and is hidden below 1100 px.
 */
export function ContentsNav({
  items,
  active,
  onGo,
  kind = "link",
}: {
  items: readonly ContentsItem[];
  active: string;
  onGo: (id: string) => void;
  /** `link` points at the section's `#id`; `button` is for pages that also change the URL query themselves. */
  kind?: "link" | "button";
}) {
  const item = cn(
    "block border-l-[3px] border-transparent py-1.5 pl-3 text-left text-[13px] text-muted transition-colors duration-120 hover:text-ink hover:no-underline",
  );
  return (
    <nav aria-label="On this page" className="sticky top-0 hidden h-fit pt-6 min-[1100px]:block">
      <p className="m-0 mb-2 text-[13px] font-semibold text-muted">On this page</p>
      <ul className="m-0 list-none p-0">
        {items.map((i) => (
          <li key={i.id}>
            {kind === "button" ? (
              <button
                type="button"
                aria-current={active === i.id ? "location" : undefined}
                onClick={() => onGo(i.id)}
                className={cn(item, "w-full", active === i.id && "border-primary font-semibold text-ink")}
              >
                {i.label}
              </button>
            ) : (
              <a
                href={`#${i.id}`}
                onClick={(e) => {
                  e.preventDefault();
                  onGo(i.id);
                }}
                aria-current={active === i.id ? "location" : undefined}
                className={cn(item, active === i.id && "border-primary font-semibold text-ink")}
              >
                {i.label}
              </a>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}
