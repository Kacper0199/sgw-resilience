import { defineConfig } from "@playwright/test";

const PORT = Number(process.env.SGW_E2E_PORT ?? 64220);
const API = process.env.SGW_E2E_API ?? "";
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8080"))
  throw new Error(
    "SGW_E2E_API must name a private API (http://127.0.0.1:<port>), never the shared stack on 8080",
  );

/** Replay clock controls and Load moment against a private API and database (CA #3 and #4). */
export default defineConfig({
  testDir: ".",
  testMatch: /demo-moments\.spec\.ts/,
  globalSetup: "./scenario-jump.setup.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
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
