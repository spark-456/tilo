import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const title =
  "Research every practical route for the autumn launch, compare the tradeoffs, and prepare the complete recommendation for the team";
const evidence = resolve(process.cwd(), "../../agy-bridge/evidence/R-HEADER");

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`R-HEADER ${width} ${theme} keeps a long title clear of progress`, async ({ page }) => {
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/world/k1");
      const heading = page.locator("h1.park-world-h1");
      await expect(heading).toBeVisible();
      await heading.evaluate((node, value) => {
        node.textContent = value;
        node.setAttribute("title", value);
      }, title);
      if (theme === "dark")
        await page.locator("[data-park]").evaluate((node) => node.setAttribute("data-time", "night"));
      await page.evaluate(() => document.fonts.ready.then(() => undefined));

      await expect(heading).toHaveAttribute("title", title);
      const lines = await heading.evaluate((node) => {
        const style = getComputedStyle(node);
        return node.getBoundingClientRect().height / Number.parseFloat(style.lineHeight);
      });
      expect(lines).toBeLessThanOrEqual(2.1);
      const header = page.locator(".park-world-head");
      expect(await header.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
      await page.screenshot({
        path: resolve(evidence, `${width}-${theme}.png`),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}
