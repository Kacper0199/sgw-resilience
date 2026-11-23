import { expect, type Page, test } from "@playwright/test";
import { login, USER } from "./support/login";

const SIZES = [
  { width: 1288, height: 742 },
  { width: 1512, height: 900 },
] as const;

const ROUTES = [
  "/",
  "/map",
  "/forecast",
  "/crews",
  "/water",
  "/ask",
  "/brief",
  "/after-action",
  "/health",
  "/readiness",
  "/notifications",
  "/admin",
  "/help",
];

/**
 * Pages whose content is a long column of sections (a document or a report): the shell's main area may scroll as a
 * whole, never a region nested inside it. Decisions, Map, Readiness, Admin and Ask are panes that fit the screen.
 * Water and System health fit on the live demo data (checked at 1288x742 and 1512x900); the mock fixtures carry more
 * steps and datasets, so they stay here.
 */
const READING_PAGES = new Set([
  "/forecast",
  "/crews",
  "/water",
  "/brief",
  "/after-action",
  "/health",
  "/help",
  "/notifications",
]);

/**
 * Regions that may scroll because their content is a genuinely long list or a long pane body. Each one carries
 * data-scroll-region with the reason: decision-list, decision-detail, map-panel, readiness-detail, people-list,
 * person-detail, admin-tab, ask-chat, ask-history, ask-sources. Nothing else may show a scrollbar, and nothing
 * may scroll sideways.
 */
const ALLOWED_REGION = "[data-scroll-region]";

type Offender = { where: string; axis: "x" | "y"; scroll: number; client: number };

async function scrollbars(page: Page, route: string): Promise<Offender[]> {
  return page.evaluate(
    ({ route: r, reading, allowed }) => {
      const out: { where: string; axis: "x" | "y"; scroll: number; client: number }[] = [];
      const name = (el: Element) => {
        const id = el.getAttribute("data-testid") ?? el.getAttribute("aria-label") ?? el.id;
        return `${el.tagName.toLowerCase()}${id ? `[${id}]` : ""}.${String(el.className).split(" ").slice(0, 3).join(".")}`;
      };
      const roots = [document.documentElement, ...Array.from(document.body.querySelectorAll("*"))];
      for (const el of roots) {
        const style = getComputedStyle(el);
        if (style.display === "none" || style.visibility === "hidden") continue;
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        const isMain = el.id === "main";
        const check = (axis: "x" | "y", overflow: string, scroll: number, client: number) => {
          if (!["auto", "scroll"].includes(overflow)) return;
          if (scroll - client > 1) out.push({ where: name(el), axis, scroll, client });
        };
        check("x", style.overflowX, el.scrollWidth, el.clientWidth);
        const scrolls = ["auto", "scroll"].includes(style.overflowY) && el.scrollHeight - el.clientHeight > 1;
        if (scrolls && !isMain) {
          for (let up = el.parentElement; up; up = up.parentElement) {
            const o = getComputedStyle(up).overflowY;
            if (["auto", "scroll"].includes(o) && up.scrollHeight - up.clientHeight > 1) {
              out.push({
                where: `nested ${name(el)} in ${name(up)}`,
                axis: "y",
                scroll: el.scrollHeight,
                client: el.clientHeight,
              });
              break;
            }
          }
        }
        if ((isMain && reading.includes(r)) || el.closest(allowed)) continue;
        check("y", style.overflowY, el.scrollHeight, el.clientHeight);
      }
      return out;
    },
    { route, reading: [...READING_PAGES], allowed: ALLOWED_REGION },
  ) as Promise<Offender[]>;
}

async function tabNames(page: Page): Promise<string[]> {
  return page
    .locator("main [role=tab]:not([inert])")
    .evaluateAll((tabs) => tabs.map((t) => (t.textContent ?? "").trim()));
}

for (const size of SIZES) {
  test.describe(`no default scrollbars at ${size.width}x${size.height}`, () => {
    test.use({ viewport: size });

    test("the sign-in page fits without a scrollbar", async ({ page }) => {
      await page.goto("/login");
      await page.getByRole("heading", { name: "Sign in" }).waitFor();
      expect(await scrollbars(page, "/login")).toEqual([]);
    });

    test("every route and main tab fits without a scrollbar", async ({ page }) => {
      test.setTimeout(240_000);
      await page.addInitScript(() => localStorage.setItem("sgw.theme", "light"));
      await login(page, USER.admin);
      const failures: string[] = [];
      for (const route of ROUTES) {
        await page.goto(route);
        await page.locator("main h1, main h2").first().waitFor();
        await page.waitForTimeout(700);
        const found = await scrollbars(page, route);
        failures.push(...found.map((o) => `${route} ${o.axis} ${o.where} ${o.scroll}/${o.client}`));
        for (const name of await tabNames(page)) {
          const tab = page.locator("main [role=tab]:not([inert])", { hasText: name }).first();
          if (!(await tab.isVisible())) continue;
          await tab.click({ timeout: 3000 });
          await page.waitForTimeout(150);
          const inTab = await scrollbars(page, route);
          failures.push(
            ...inTab.map((o) => `${route} [${name}] ${o.axis} ${o.where} ${o.scroll}/${o.client}`),
          );
        }
      }
      expect(failures).toEqual([]);
    });
  });
}
