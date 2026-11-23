import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

/** The production policy, read from the Caddyfile that serves the app. */
function caddyCsp(): string {
  const file = readFileSync(resolve("..", "infra/caddy/Caddyfile"), "utf8");
  const match = /Content-Security-Policy\s+"([^"]+)"/.exec(file);
  if (!match?.[1]) throw new Error("Content-Security-Policy not found in infra/caddy/Caddyfile");
  return match[1];
}

test("the built app runs under the Caddy CSP: no violation and the stored dark theme applies", async ({
  page,
}) => {
  const csp = caddyCsp();
  await page.route("**/*", async (route) => {
    try {
      const response = await route.fetch();
      await route.fulfill({
        status: response.status(),
        body: await response.body(),
        headers: { ...response.headers(), "content-security-policy": csp },
      });
    } catch {
      // requests still in flight when the page closes at the end of the test
    }
  });
  await page.addInitScript(() => {
    localStorage.setItem("sgw.theme", "dark");
    (window as unknown as { __csp: string[] }).__csp = [];
    document.addEventListener("securitypolicyviolation", (e) =>
      (window as unknown as { __csp: string[] }).__csp.push(`${e.violatedDirective} ${e.blockedURI}`),
    );
  });
  const consoleCsp: string[] = [];
  page.on("console", (m) => /content security policy/i.test(m.text()) && consoleCsp.push(m.text()));

  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).toEqual([]);
  expect(consoleCsp).toEqual([]);
});
