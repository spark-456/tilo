import { writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { type TextProblem, findTextProblems, stretchTitles } from "./support/textOverflow";

// UX-SMOOTH (owner, 21 Oct: "many pages have texts bleeding"): on every Park page, at 1440, 1280, 1024, 768 and 390
// wide, in the light and the dark theme, no text is clipped without a tooltip, spills out of its box, is cut by a
// clipping parent or is drawn over other text; then again with every title slot holding a long real run name. The
// fixture app (no VITE_TILO_API_URL). Run on a production preview, one worker:
//   TILO_WEB_PROD=1 TILO_WEB_PORT=<own port> pnpm exec playwright test e2e/ux-audit.text-overflow.spec.ts
//   --project=chromium --no-deps --workers=1
// UX_OVERFLOW_DUMP=<file.json> writes every finding instead of failing (for an audit).

const PAGES = [
  "/",
  "/chat",
  "/worlds",
  "/world/k1",
  "/world/hires",
  "/skills",
  "/needs",
  "/ledger",
  "/agenda",
  "/team",
  "/connectors",
  "/profile",
  "/settings",
  "/library",
  "/more",
] as const;
const WIDTHS = [1440, 1280, 1024, 768, 390] as const;
// Twenty loads per page in one test: no trace (it stalled the browser on a busy laptop).
test.use({ trace: "off" });
const THEMES = ["day", "night"] as const;
const DUMP = process.env.UX_OVERFLOW_DUMP;
const found: Record<string, TextProblem[]> = {};

for (const path of PAGES) {
  test(`UX_SMOOTH no text is clipped, spills or overlaps on ${path}`, async ({
    browser,
    baseURL,
  }) => {
    test.setTimeout(300_000);
    const problems: string[] = [];
    for (const theme of THEMES) {
      const ctx = await browser.newContext({ ...(baseURL ? { baseURL } : {}) });
      await ctx.addInitScript((time) => {
        try {
          sessionStorage.setItem("tilo-boot-seen", "1");
          localStorage.setItem("tilo.time", time);
        } catch {
          // storage blocked: the page still loads in the default theme
        }
      }, theme);
      const page = await ctx.newPage();
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
        for (const stretched of [false, true]) {
          await page.goto(path);
          await page.locator("main").first().waitFor();
          await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
          await page.evaluate(() => document.fonts.ready.then(() => undefined));
          if (stretched) await stretchTitles(page);
          const list = await findTextProblems(page);
          const key = `${path} ${width} ${theme}${stretched ? " long" : ""}`;
          found[key] = list;
          for (const p of list)
            problems.push(`${key}: ${p.kind} ${p.px}px "${p.text}" (${p.where})`);
        }
      }
      await ctx.close();
    }
    if (DUMP) {
      writeFileSync(
        DUMP.replace(/\.json$/, `${path.replace(/\W+/g, "_")}.json`),
        JSON.stringify(found, null, 1),
      );
      return;
    }
    expect(problems, problems.join("\n")).toEqual([]);
  });
}
