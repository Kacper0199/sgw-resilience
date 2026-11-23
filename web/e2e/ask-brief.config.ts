import { defineConfig } from "@playwright/test";

const PORT = Number(process.env.SGW_E2E_PORT ?? 64400);

/** Own port so parallel runs never share a dev server. */
export default defineConfig({
  testDir: ".",
  testMatch: /(ask|brief)\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, viewport: { width: 1440, height: 900 } },
  webServer: {
    command: `pnpm exec vite --port ${PORT} --strictPort --mode mock`,
    cwd: "..",
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
