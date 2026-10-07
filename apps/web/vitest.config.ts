import { defineConfig } from "vitest/config";

// Unit tests only (apps/web/src/**/*.test.ts, apps/web/test-support). End-to-end
// / layout / renderer / accessibility acceptance tests live under apps/web/e2e
// and run with Playwright (see playwright.config.ts), not Vitest.
export default defineConfig({
  // vite-node leaves "%20" in file:// import ids, and this repo's path has spaces.
  resolve: { alias: [{ find: /%20/g, replacement: " " }] },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    exclude: ["e2e/**", "node_modules/**"],
    // A jsdom render is a few hundred ms alone but 6 s+ while a dozen ts.createProgram typecheck tests run in
    // parallel workers (the 5 s default timed out Profile.styles once). A timeout only has to catch a hang.
    testTimeout: 30_000,
    // Each *.typecheck.test.ts builds a ts program synchronously (up to ~80 s with 15 workers on 16 cores), which blocks
    // its worker past vitest's 60 s RPC timeout: "Timeout calling onTaskUpdate" fails the run with every test green.
    // 6 workers: no RPC errors in 3 runs (15 workers: errors in 4 of 4), and the park suite takes ~118 s instead of ~88 s.
    maxWorkers: 6,
  },
});
