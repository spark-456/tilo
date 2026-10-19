// `just parity [pages]` (WEB-PARITY, dev/test only): runs the opt-in `parity` Playwright project, which
// captures the design reference and our /park pages and writes apps/web/parity-report/. A first
// argument that does not start with "-" limits the pages ("team" or "team,profile"; same as the
// PARITY_PAGES env var); the rest goes to Playwright. Reports diffs, never fails on one.
import { spawnSync } from "node:child_process";

const args = process.argv.slice(2);
const pages = args.length > 0 && !args[0].startsWith("-") ? args.shift() : "";
const result = spawnSync("pnpm", ["exec", "playwright", "test", "--project=parity", ...args], {
  cwd: new URL("..", import.meta.url),
  stdio: "inherit",
  shell: process.platform === "win32",
  env: { ...process.env, TILO_PARITY: "1", ...(pages ? { PARITY_PAGES: pages } : {}) },
});
process.exit(result.status ?? 1);
