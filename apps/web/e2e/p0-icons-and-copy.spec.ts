import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "P0-ICONS-AND-COPY",
);

const PAGES = [
  { path: "/", name: "Home", heading: "Tilo" },
  { path: "/worlds", name: "Worlds", heading: "Worlds" },
  { path: "/skills", name: "Skills", heading: "Skills" },
  { path: "/team", name: "Team", heading: "Team" },
  { path: "/ledger", name: "Ledger", heading: "Ledger" },
  { path: "/connectors", name: "Connectors", heading: "Connectors" },
  { path: "/agenda", name: "Agenda", heading: "Agenda" },
] as const;

for (const width of [1440, 390] as const) {
  for (const pageInfo of PAGES) {
    test(`P0-ICONS-AND-COPY ${width} ${pageInfo.name}`, async ({ page }) => {
      test.setTimeout(60_000);
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto(pageInfo.path);
      await page.waitForLoadState("domcontentloaded");
      await page.evaluate(() => document.fonts.ready.then(() => undefined));

      const shotPath = `${width}-${pageInfo.name}.png`;
      await page.screenshot({
        path: resolve(evidence, shotPath),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}
