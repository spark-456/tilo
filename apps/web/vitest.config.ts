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
  },
});
