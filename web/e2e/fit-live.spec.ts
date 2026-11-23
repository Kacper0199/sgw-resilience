import { expect, test } from "@playwright/test";
import { login, USER } from "./support/login";

const SIZES = [
  { width: 1288, height: 742 },
  { width: 1512, height: 900 },
] as const;

for (const size of SIZES) {
  test.describe(`live data fits at ${size.width}x${size.height}`, () => {
    test.use({ viewport: size });

    for (const [route, region] of [
      ["/", "decision-list"],
      ["/readiness", "readiness-list"],
    ] as const) {
      test(`${route} ${region} opens without a scrollbar`, async ({ page }) => {
        await page.addInitScript(() => localStorage.setItem("sgw.theme", "light"));
        await login(page, USER.admin);
        await page.goto(route);
        await page.locator("main h1").first().waitFor();
        await page.waitForTimeout(1200);
        const overflow = await page
          .locator(`[data-scroll-region="${region}"]`)
          .evaluate((el) => ({ scroll: el.scrollHeight, client: el.clientHeight }));
        expect(overflow.scroll - overflow.client).toBeLessThanOrEqual(1);
      });
    }

    for (const route of ["/water", "/health"]) {
      test(`${route} opens without a scrollbar`, async ({ page }) => {
        await page.addInitScript(() => localStorage.setItem("sgw.theme", "light"));
        await login(page, USER.admin);
        await page.goto(route);
        await page.locator("main h1").first().waitFor();
        await page.waitForTimeout(1200);
        const overflow = await page
          .locator("#main")
          .evaluate((el) => ({ scroll: el.scrollHeight, client: el.clientHeight }));
        expect(overflow.scroll - overflow.client).toBeLessThanOrEqual(1);
      });
    }
  });
}
