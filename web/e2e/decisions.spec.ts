import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { login as signInPage, switchUser, USER } from "./support/login";

const PS17 = "PRP-PS17-FDR2207-PRIO";
const CREWS = "PRP-CREW-AIK-0926A";
const SITREP = "PRP-SITREP-PRELANDFALL";
const SHOTS = process.env.SGW_SHOTS;

declare global {
  interface Window {
    __sgwStory?: { start: (advisory: "N" | "N+1") => void; advance: (advisory: "N" | "N+1") => void };
    __anim?: number;
  }
}

async function login(page: Page, who: string) {
  await signInPage(page, who, {
    beforeSignIn: async (p) => {
      await p.waitForFunction(() => Boolean(window.__sgwStory));
      await p.evaluate(() => window.__sgwStory?.start("N"));
    },
  });
  await expect(page.getByTestId("decision-row").first()).toBeVisible();
}

const rowIds = (page: Page) =>
  page.getByTestId("decision-row").evaluateAll((els) => els.map((e) => e.getAttribute("data-row-id")));
const row = (page: Page, id: string) => page.locator(`[data-testid="decision-row"][data-row-id="${id}"]`);
const open = async (page: Page, id: string) => {
  await row(page, id).click();
  await expect(page).toHaveURL(new RegExp(`d=${id}`));
};
/** Counts script-driven animations (the reorder) on the queue list; CSS hover transitions are left out. */
const watchListAnimations = (page: Page) =>
  page.evaluate(() => {
    window.__anim = 0;
    setInterval(() => {
      const n = document.getAnimations().filter((a) => {
        if (a instanceof CSSTransition || a instanceof CSSAnimation) return false;
        const target = (a.effect as KeyframeEffect | null)?.target;
        return Boolean(target?.closest?.("[data-queue]"));
      }).length;
      window.__anim = Math.max(window.__anim ?? 0, n);
    }, 16);
  });
const advance = (page: Page) => page.evaluate(() => window.__sgwStory?.advance("N+1"));

async function seriousViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  return results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

async function consoleErrors(page: Page): Promise<string[]> {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test.describe("queue", () => {
  test("groups the signer's own work on top, then time buckets, with sort, filters and a page footer", async ({
    page,
  }) => {
    const errors = await consoleErrors(page);
    await login(page, USER.commander);
    const labels = await page.locator('th[scope="colgroup"]').allTextContents();
    expect(labels[0]).toMatch(/^Waiting on you\s*2$/);
    expect(labels.slice(1).join(" ")).toMatch(/Next hour/);
    const ids = await rowIds(page);
    expect(ids.slice(0, 2)).toEqual([SITREP, PS17]);
    await expect(page.getByTestId("page-range")).toHaveText("1–6 of 6");

    await page.getByRole("combobox", { name: "Utility" }).selectOption("water");
    await expect(page).toHaveURL(/domain=water/);
    await expect.poll(() => rowIds(page)).toEqual([PS17, "PRP-BWN-READY"]);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("(2)");
    await page.getByRole("combobox", { name: "Owner" }).selectOption({ label: "Water operations" });
    await expect(page).toHaveURL(/owner=water_operations/);
    await page.getByRole("combobox", { name: "Utility" }).selectOption("all");
    await page.getByRole("combobox", { name: "Owner" }).selectOption("all");

    await page.getByRole("tab", { name: /^Waiting on you/ }).click();
    await expect.poll(() => rowIds(page)).toEqual([SITREP, PS17]);
    await page.getByRole("tab", { name: /^All open/ }).click();

    await page.getByRole("button", { name: "Sort by severity" }).click();
    await expect(page).toHaveURL(/sort=severity/);
    await expect(page.locator('th[scope="colgroup"]')).toHaveCount(0);
    await page.getByRole("button", { name: /Sort by deadline/ }).click();
    await expect(page.locator('th[scope="colgroup"]').first()).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("keyboard: j and k move, Enter focuses the case, o opens the page, Escape closes", async ({
    page,
  }) => {
    await login(page, USER.commander);
    const first = (await rowIds(page))[0] as string;
    await expect(row(page, first)).toHaveAttribute("data-selected", "true");
    await page.keyboard.press("j");
    await expect(page.getByTestId("decision-row").nth(1)).toHaveAttribute("data-selected", "true");
    await page.keyboard.press("k");
    await expect(row(page, first)).toHaveAttribute("data-selected", "true");
    await expect(async () => {
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("inspector").getByRole("heading", { level: 3 })).toBeFocused({
        timeout: 500,
      });
    }).toPass();
    await page.keyboard.press("Escape");
    await expect(page.getByText("Select a decision to see its details.")).toBeVisible();
    await page.getByTestId("decision-row").nth(1).click();
    await page.keyboard.press("o");
    await expect(page).toHaveURL(/\/decisions\/PRP-/);
    await expect(page.getByTestId("case-page")).toBeVisible();
  });
});

test.describe("toolbar and layout", () => {
  test("find, Timing and the Closed tab narrow the table; Clear removes the filters; the key strip counts open work", async ({
    page,
  }) => {
    await login(page, USER.commander);
    const strip = page.getByRole("term").filter({ hasText: "Open decisions" }).locator("..");
    await expect(strip).toContainText("6");
    await page.getByRole("searchbox", { name: "Find a decision" }).fill("sitrep");
    await expect(page).toHaveURL(/find=sitrep/);
    await expect.poll(() => rowIds(page)).toEqual([SITREP]);
    await page.getByRole("searchbox", { name: "Find a decision" }).fill("");
    await page.getByRole("combobox", { name: "Timing" }).selectOption({ index: 1 });
    await expect(page).toHaveURL(/timing=/);
    const clear = page.getByRole("button", { name: "Clear", exact: true });
    await expect(clear).toBeVisible();
    await expect.poll(async () => (await rowIds(page)).length).toBeLessThan(6);
    await clear.click();
    await expect.poll(async () => (await rowIds(page)).length).toBe(6);
    await page.getByRole("tab", { name: /^Closed/ }).click();
    await expect(page).toHaveURL(/q=decided/);
    await expect(page.getByText("No decisions are closed yet.")).toBeVisible();
  });

  test("on a phone there is no side pane: a row opens the full page", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, USER.commander);
    await expect(page.getByLabel("Decision details")).toHaveCount(0);
    await row(page, PS17).click();
    await expect(page).toHaveURL(new RegExp(`/decisions/${PS17}`));
    await expect(page.getByTestId("case-page")).toBeVisible();
  });
});

test.describe("shortcuts and dialogs", () => {
  test("j, k, arrows and o do nothing behind the open Sign dialog, so a signature stays on its decision", async ({
    page,
  }) => {
    await login(page, USER.logistics);
    await open(page, CREWS);
    await page.getByRole("button", { name: /^Sign as / }).click();
    const dialog = page.getByRole("dialog");
    const title = await dialog.textContent();
    const url = page.url();
    await dialog.getByRole("button", { name: "Cancel" }).focus();
    for (const key of ["j", "k", "ArrowDown", "ArrowUp", "o"]) await page.keyboard.press(key);
    await page.waitForTimeout(400);
    expect(page.url()).toBe(url);
    await expect(page.getByRole("dialog")).toHaveCount(1);
    expect(await page.getByRole("dialog").textContent()).toBe(title);
    await expect(row(page, CREWS)).toHaveAttribute("data-selected", "true");
  });

  test("arrow keys only move the selection when focus is in the queue", async ({ page }) => {
    await login(page, USER.commander);
    const first = (await rowIds(page))[0] as string;
    await page.getByRole("tab", { name: /Deadline/ }).focus();
    await page.keyboard.press("ArrowDown");
    await expect(row(page, first)).toHaveAttribute("data-selected", "true");
    await row(page, first).focus();
    await page.keyboard.press("ArrowDown");
    await expect(row(page, first)).toHaveAttribute("data-selected", "false");
  });
});

test.describe("PS-17 story", () => {
  test("advisory N+1 reorders the queue, voids the signature and shows the earlier-by chip", async ({
    page,
  }) => {
    const errors = await consoleErrors(page);
    await login(page, USER.commander);
    await expect.poll(async () => (await rowIds(page)).slice(0, 2)).toEqual([SITREP, PS17]);

    await open(page, CREWS);
    await page.getByRole("tab", { name: /Signatures/ }).click();
    await expect(page.getByTestId("approval-head")).toHaveText("Waiting for Logistics");
    await expect(page.getByTestId("signature-row").first()).toContainText("Incident Commander");
    await expect(page.getByTestId("signature-row").first()).toContainText("v1");
    await expect(page.getByTestId("void-banner")).toHaveCount(0);

    await watchListAnimations(page);
    await advance(page);

    await expect.poll(async () => (await rowIds(page)).slice(0, 3)).toEqual([CREWS, PS17, SITREP]);
    await expect(page.getByTestId("reorder-live")).toContainText("moved to");
    await expect(page.getByTestId("reorder-live")).toContainText("deadline earlier by");
    expect(await page.evaluate(() => window.__anim)).toBeGreaterThan(0);
    await expect(row(page, PS17).getByTestId("row-clock")).toHaveAttribute("data-flash", "true");

    await expect(page.getByTestId("void-banner")).toContainText("Version 2 replaced an earlier version");
    await expect(page.getByTestId("void-banner")).toContainText("Command signed v1");
    await expect(page.getByTestId("voided-row")).toContainText("No longer valid as of v2");
    await expect(page.getByTestId("approval-head")).toHaveText("Waiting for Command (you), Logistics");
    await expect(row(page, CREWS)).toBeVisible();

    await open(page, PS17);
    await expect(page.getByTestId("shift-chip")).toHaveText("Earlier by 1 h 16 m, was 00:45 ET (04:45Z)");
    await expect(page.getByTestId("case-header")).toContainText("Act now");
    expect(errors).toEqual([]);
  });

  test("a signature cannot be sent on a version that changed: the dialog asks for a review first", async ({
    page,
  }) => {
    await login(page, USER.logistics);
    await open(page, CREWS);
    await page.getByRole("button", { name: /^Sign as / }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("button", { name: "Sign", exact: true })).toBeVisible();
    await advance(page);
    await expect(dialog.getByRole("button", { name: "Review v2" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Sign", exact: true })).toHaveCount(0);
    await expect(dialog.getByRole("alert")).toContainText("changed to version 2");
    await dialog.getByRole("button", { name: "Review v2" }).click();
    await expect(dialog.getByRole("button", { name: "Sign", exact: true })).toBeVisible();
  });

  test("reduced motion reorders at once and still outlines the changed clock", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await login(page, USER.commander);
    await watchListAnimations(page);
    await advance(page);
    await expect.poll(async () => (await rowIds(page)).slice(0, 3)).toEqual([CREWS, PS17, SITREP]);
    expect(await page.evaluate(() => window.__anim)).toBe(0);
    await expect(row(page, PS17).getByTestId("row-clock")).toHaveAttribute("data-flash", "true");
  });
});

test.describe("case tabs", () => {
  test("Basis: timing reasons behind Info, waterfall with Now, ET and Z, and the source lines", async ({
    page,
  }) => {
    await login(page, USER.commander);
    await open(page, PS17);
    await expect(page.getByTestId("case-header")).toContainText("Can wait");
    await expect(page.getByTestId("case-header")).toContainText("of cases");
    await page.getByRole("button", { name: "Why this timing" }).click();
    await expect(page.getByTestId("why-block")).toBeVisible();
    await page.keyboard.press("Escape");
    const water = page.getByTestId("waterfall");
    await expect(water).toBeVisible();
    await expect(page.getByTestId("waterfall-now")).toBeAttached();
    await expect(water).toContainText("ET (UTC)");
    await page.getByRole("button", { name: "Where the numbers come from" }).click();
    await expect(page.getByRole("dialog")).toContainText("Time to hook up a portable generator");
    await expect(page.getByRole("dialog")).toContainText("Water network model: PS-17 pressure floor");
  });

  test("Path: numbered chain, blocked-by link selects the other case, red only on negative slack", async ({
    page,
  }) => {
    await login(page, USER.commander);
    await open(page, PS17);
    await page.getByRole("tab", { name: /Sequence/ }).click();
    const steps = page.getByTestId("chain-step");
    await expect(steps).toHaveCount(2);
    await expect(steps.nth(0)).toContainText("Pre-position crews");
    await expect(page.getByTestId("chain-link")).toHaveAttribute("data-negative", "false");
    await page.getByText("Depends on", { exact: true }).locator("..").getByRole("button").click();
    await expect(page).toHaveURL(new RegExp(`d=${CREWS}`));
    await expect(page.getByTestId("case-header")).toContainText("Pre-position crews");
  });

  test("Evidence: attached records and customer equivalents", async ({ page }) => {
    await login(page, USER.commander);
    await open(page, PS17);
    await expect(page.getByTestId("evidence-item").first()).toBeVisible();
    await expect(page.getByTestId("ce-breakdown")).toContainText("Customers counted");
    await expect(page.getByTestId("ce-breakdown")).toContainText("3,840");
    await page.getByRole("button", { name: "How the customers are counted" }).click();
    await expect(page.getByRole("dialog", { name: "How the customers are counted" })).toContainText(
      "plus 2,000 for a critical facility",
    );
  });

  test("History: the ledger timeline", async ({ page }) => {
    await login(page, USER.commander);
    await open(page, CREWS);
    await page.getByRole("tab", { name: /History/ }).click();
    await expect(page.getByTestId("timeline")).toContainText("Signature recorded");
  });

  test("the full case page shows every section and goes back to the queue", async ({ page }) => {
    await login(page, USER.commander);
    await open(page, PS17);
    await page.getByRole("link", { name: "Open full page" }).click();
    await expect(page).toHaveURL(new RegExp(`/decisions/${PS17}`));
    const view = page.getByTestId("case-page");
    for (const id of ["basis", "approval-card", "path", "evidence", "history"]) {
      await expect(view.getByTestId(id)).toBeVisible();
    }
    await expect(page.getByRole("link", { name: "Decisions", exact: true }).first()).toBeVisible();
    await page.getByRole("link", { name: "Decisions" }).last().click();
    await expect(page).toHaveURL(new RegExp(`d=${PS17}`));
  });
});

test.describe("approval", () => {
  test("two-function T3 signature, then the envelope chip appears on the re-signed crew decision", async ({
    page,
  }) => {
    await login(page, USER.commander);
    await advance(page);
    await open(page, CREWS);
    await page.getByRole("button", { name: /^Sign as / }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Sign", exact: true }).click();
    const pw = dialog.getByLabel("Confirm your password to continue");
    if (await pw.isVisible({ timeout: 1500 }).catch(() => false)) {
      await pw.fill("demo");
      await dialog.getByRole("button", { name: "Sign", exact: true }).click();
    }
    await expect(page.getByText("Signed. Waiting for the other team.")).toBeVisible();
    await switchUser(page, USER.logistics);
    await page.getByTestId("decision-row").first().waitFor();
    await open(page, CREWS);
    await page.getByRole("button", { name: /^Sign as / }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Sign", exact: true }).click();
    const pw2 = dialog.getByLabel("Confirm your password to continue");
    if (await pw2.isVisible({ timeout: 1500 }).catch(() => false)) {
      await pw2.fill("demo");
      await dialog.getByRole("button", { name: "Sign", exact: true }).click();
    }
    await expect(page.getByText("Signed. The decision is approved.")).toBeVisible();
    await expect(page.getByTestId("envelope-chip")).toContainText("Pre-approved limits, valid until");
    await page.getByRole("tab", { name: /Signatures/ }).click();
    await expect(page.getByText("Changes inside the pre-approved limits")).toBeVisible();
  });

  test("send back needs a reason; break-glass is a secondary text action with the co-sign note", async ({
    page,
  }) => {
    await login(page, USER.commander);
    await open(page, PS17);
    await page.getByRole("button", { name: "Send back" }).click();
    let dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("button", { name: "Send back", exact: true })).toBeDisabled();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await page.getByRole("button", { name: "Approve alone…" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("within 24 hours");
    await expect(dialog.getByRole("button", { name: "Approve alone", exact: true })).toBeDisabled();
    await dialog.getByLabel("Why is this an emergency?").fill("Generator failed at PS-17");
    await dialog.getByRole("button", { name: "Approve alone", exact: true }).click();
    const pw = dialog.getByLabel("Confirm your password to continue");
    if (await pw.isVisible({ timeout: 1500 }).catch(() => false)) {
      await pw.fill("demo");
      await dialog.getByRole("button", { name: "Sign", exact: true }).click();
    }
    await page.getByRole("tab", { name: /Signatures/ }).click();
    await expect(page.getByTestId("break-glass-card")).toContainText("Generator failed at PS-17");
    await expect(page.getByTestId("break-glass-card")).toContainText("must co-sign by");
  });
});

test.describe("accessibility and info tips", () => {
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 },
  ]) {
    test(`every InfoTip on the home and each tab stays in the viewport at ${viewport.width}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await login(page, USER.commander);
      await open(page, PS17);
      for (const tab of ["Deadline", "Signatures", "Sequence", "History"]) {
        await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
        const triggers = page.locator('button[aria-label^="What does"]');
        const count = await triggers.count();
        for (let i = 0; i < count; i++) {
          const trigger = triggers.nth(i);
          if (!(await trigger.isVisible())) continue;
          await trigger.scrollIntoViewIfNeeded();
          await trigger.click();
          const bubble = page.locator('[data-testid^="infotip-"]');
          await expect(bubble).toBeVisible();
          const g = await bubble.evaluate((el) => {
            const r = el.getBoundingClientRect();
            return {
              l: r.left,
              t: r.top,
              r: r.right,
              b: r.bottom,
              w: r.width,
              vw: window.innerWidth,
              vh: window.innerHeight,
            };
          });
          expect(g.l, `${tab} tip ${i}`).toBeGreaterThanOrEqual(0);
          expect(g.t, `${tab} tip ${i}`).toBeGreaterThanOrEqual(0);
          expect(g.r, `${tab} tip ${i}`).toBeLessThanOrEqual(g.vw);
          expect(g.b, `${tab} tip ${i}`).toBeLessThanOrEqual(g.vh);
          expect(g.w).toBeLessThanOrEqual(281);
          await page.keyboard.press("Escape");
          await expect(bubble).toHaveCount(0);
        }
      }
    });
  }

  for (const theme of ["light", "dark"] as const) {
    test(`axe finds no serious violations on the queue, each tab and the case page (${theme})`, async ({
      page,
    }) => {
      await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
      await login(page, USER.commander);
      await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
      await open(page, PS17);
      expect(await seriousViolations(page), "queue and basis").toEqual([]);
      for (const tab of ["Signatures", "Sequence", "History"]) {
        await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
        expect(await seriousViolations(page), tab).toEqual([]);
      }
      await page.goto(`/decisions/${PS17}`);
      await expect(page.getByTestId("case-page")).toBeVisible();
      expect(await seriousViolations(page), "case page").toEqual([]);
    });
  }
});

const shots = SHOTS ? test.describe : () => undefined;

shots("screenshots", () => {
  const sizes = [
    { name: "1440", width: 1440, height: 900 },
    { name: "1920", width: 1920, height: 1080 },
  ];
  for (const size of sizes) {
    for (const theme of ["light", "dark"] as const) {
      test(`queue, tabs and case page at ${size.name} ${theme}`, async ({ page }) => {
        await page.setViewportSize({ width: size.width, height: size.height });
        await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
        await login(page, USER.commander);
        await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
        const file = (n: string) => `${SHOTS}/${n}-${size.name}-${theme}.png`;
        await open(page, PS17);
        await page.waitForTimeout(600);
        await page.screenshot({ path: file("queue-basis") });
        await advance(page);
        await page.waitForTimeout(900);
        await page.screenshot({ path: file("queue-n1-chip") });
        if (size.name === "1440" && theme === "light") {
          await page.evaluate(() => {
            document.documentElement.style.filter = "grayscale(1)";
          });
          await page.screenshot({ path: `${SHOTS}/queue-n1-chip-1440-grayscale.png` });
          await page.evaluate(() => {
            document.documentElement.style.filter = "";
          });
        }
        for (const tab of ["Signatures", "Sequence", "History"]) {
          await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
          await page.waitForTimeout(150);
          await page.screenshot({ path: file(`tab-${tab.toLowerCase()}`) });
        }
        await open(page, CREWS);
        await page.getByRole("tab", { name: /Signatures/ }).click();
        await page.screenshot({ path: file("crews-void") });
        await open(page, PS17);
        await page.getByRole("link", { name: "Open full page" }).click();
        await expect(page.getByTestId("case-page")).toBeVisible();
        await page.screenshot({ path: file("case-page"), fullPage: true });
      });
    }
  }
});
