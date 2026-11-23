import { expect, test } from "@playwright/test";
import { login, USER } from "./support/login";

const SIZES = [
  { width: 1288, height: 742 },
  { width: 1512, height: 900 },
] as const;

test("the owner records a readiness result at the pre-season review; others see no control", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, USER.dutyManager);
  await page.goto("/readiness?item=DC-RDY-GEN-PS52-LOADTEST");
  const detail = page.getByTestId("readiness-detail");
  await detail.getByRole("button", { name: "Record result" }).click();
  const dialog = page.getByTestId("record-result-dialog");
  await expect(dialog).toContainText("Recorded as of the pre-season review, 6 May 2024.");
  await dialog.getByLabel("Note").fill("Load test passed for 2 h");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByTestId("readiness-summary")).toContainText("3 of 6 ready");
  await expect(detail.getByTestId("readiness-result")).toContainText("Load test passed for 2 h");
  expect(errors).toEqual([]);
});

test("a person who owns no check gets no Record result", async ({ page }) => {
  await login(page, USER.executive);
  await page.goto("/readiness?item=DC-RDY-GEN-PS52-LOADTEST");
  await expect(page.getByTestId("readiness-detail")).toContainText("What is missing");
  await expect(page.getByRole("button", { name: "Record result" })).toHaveCount(0);
});

test("the water stepper shows the clean sample count from the register", async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem("sgw.mock.zone_rules", "1"));
  await login(page, USER.waterLead);
  await page.goto("/water?tab=advisories");
  const rows = page.getByTestId("bwa-row");
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(2)).toContainText("Samples 1/2");
  await expect(rows.nth(1)).toContainText("Samples 2/2");
});

for (const size of SIZES) {
  test(`the briefing prints on A4 without the navigation at ${size.width}`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.addInitScript(() => localStorage.setItem("sgw.theme", "dark"));
    await login(page, USER.executive);
    await page.goto("/brief");
    await expect(page.getByRole("button", { name: "Print / Save as PDF" })).toBeVisible();
    await page.emulateMedia({ media: "print" });
    await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(page.getByRole("navigation", { name: "Main menu" })).toBeHidden();
    await expect(page.getByRole("button", { name: "Print / Save as PDF" })).toBeHidden();
    await expect(page.locator("#sitrep")).toBeVisible();
    const clipped = await page.evaluate(() => {
      const main = document.getElementById("main");
      return main ? main.scrollHeight - main.clientHeight : -1;
    });
    expect(clipped).toBeLessThanOrEqual(1);
    const pdf = await page.pdf({ preferCSSPageSize: true });
    expect(pdf.byteLength).toBeGreaterThan(1000);
    await page.evaluate(() => window.dispatchEvent(new Event("afterprint")));
    await page.emulateMedia({ media: "screen" });
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  });
}
