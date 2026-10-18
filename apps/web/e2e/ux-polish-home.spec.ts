import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "UX-POLISH",
);

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`UX-POLISH-HOME ${width} ${theme} has calm controls and no overlap`, async ({ page }) => {
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1 })).toContainText(
        /Good (morning|afternoon|evening)/,
        { timeout: 120_000 },
      );
      if (theme === "dark") {
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      }
      await page.evaluate(() => document.fonts.ready.then(() => undefined));

      const audit = await page.evaluate(() => {
        const links = [...document.querySelectorAll<HTMLAnchorElement>(".park-home-root a")];
        const unnamedIconButtons = [
          ...document.querySelectorAll<HTMLButtonElement>(".park-home-root button"),
        ]
          .filter((button) => button.offsetParent !== null)
          .filter((button) => {
            const text = (button.textContent ?? "").trim();
            const name = button.getAttribute("aria-label") ?? button.getAttribute("title") ?? text;
            return button.querySelector("svg, img") !== null && name.trim() === "";
          }).length;
        return {
          overflows: document.documentElement.scrollWidth > document.documentElement.clientWidth,
          defaultLinks: links.filter((link) => {
            const style = getComputedStyle(link);
            return style.color === "rgb(0, 0, 238)" || style.textDecorationLine !== "none";
          }).length,
          unnamedIconButtons,
        };
      });

      expect(audit).toEqual({ overflows: false, defaultLinks: 0, unnamedIconButtons: 0 });
      await page.screenshot({
        path: resolve(evidence, `${width}-${theme}-Home.png`),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}
