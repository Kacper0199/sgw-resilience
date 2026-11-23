import { useEffect, useState } from "react";
import { ContentsNav } from "@/components/sgw";

interface Item {
  id: string;
  label: string;
}

/** Scroll-spy for the Briefing: the section in view is the active one in the shared contents list. */
export function OnThisPage({ items }: { items: readonly Item[] }) {
  const [active, setActive] = useState(items[0]?.id ?? "");

  useEffect(() => {
    const scroller = document.getElementById("main");
    if (!scroller) return;
    const update = () => {
      const atEnd = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2;
      if (atEnd) return setActive(items[items.length - 1]?.id ?? "");
      const top = scroller.getBoundingClientRect().top + 120;
      let current = items[0]?.id ?? "";
      for (const i of items) {
        const el = document.getElementById(i.id);
        if (el && el.getBoundingClientRect().top <= top) current = i.id;
      }
      setActive(current);
    };
    update();
    scroller.addEventListener("scroll", update, { passive: true });
    return () => scroller.removeEventListener("scroll", update);
  }, [items]);

  const go = (id: string) => {
    setActive(id);
    document.getElementById(id)?.scrollIntoView({ block: "start" });
  };

  return <ContentsNav items={items} active={active} onGo={go} />;
}
