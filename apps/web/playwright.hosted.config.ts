import { defineConfig, devices } from "@playwright/test";

// W22: the hosted release smoke (e2e/hosted-smoke.spec.ts). No dev server and no local origin: the spec's
// target is TILO_SMOKE_URL, and with it unset the spec skips itself. Run with `just smoke-hosted`.
// The main config ignores that spec, so `playwright test` in dev and CI never reaches the network.
export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/hosted-smoke.spec.ts",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: { trace: "retain-on-failure" },
  projects: [
    {
      name: "hosted",
      use: { ...devices["Desktop Chrome"], channel: process.env.CI ? undefined : "msedge" },
    },
  ],
});
