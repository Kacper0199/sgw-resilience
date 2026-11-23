import { defineConfig } from "@playwright/test";

const PORT = Number(process.env.SGW_E2E_PORT ?? 62501);
const API = process.env.SGW_E2E_API ?? "";
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8080"))
  throw new Error(
    "SGW_E2E_API must name a private API (http://127.0.0.1:<port>), never the shared stack on 8080",
  );

/** The D4 global ETR end to end against a private API and database: it moves the replay clock and writes proposals. */
export default defineConfig({
  testDir: ".",
  testMatch: /etr-publish\.spec\.ts/,
  globalSetup: "./etr.setup.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, viewport: { width: 1288, height: 742 } },
  webServer: {
    command: `pnpm exec vite --port ${PORT} --strictPort`,
    cwd: "..",
    env: { VITE_API_TARGET: API },
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
