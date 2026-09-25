import fs from "node:fs";
import { defineConfig, type Plugin } from "vitest/config";

// vite-node 2.1.x strips a "file://" import id's protocol but never decodes
// it, so `import(pathToFileURL(absPath).href)` (used by tokens.test.ts to
// load the generated tokens.ts) fails to match this repo's root path, which
// contains a space ("%20" undecoded). Decode such ids back to a real path.
function decodeFileUrlIds(): Plugin {
  return {
    name: "decode-file-url-ids",
    enforce: "pre",
    resolveId(source) {
      if (!/^[A-Za-z]:[\\/]/.test(source) || !source.includes("%")) return null;
      try {
        const decoded = decodeURIComponent(source);
        return fs.existsSync(decoded) ? decoded : null;
      } catch {
        return null;
      }
    },
  };
}

// Unit tests only (apps/web/src/**/*.test.ts, apps/web/test-support). End-to-end
// / layout / renderer / accessibility acceptance tests live under apps/web/e2e
// and run with Playwright (see playwright.config.ts), not Vitest.
export default defineConfig({
  plugins: [decodeFileUrlIds()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    exclude: ["e2e/**", "node_modules/**"],
  },
});
