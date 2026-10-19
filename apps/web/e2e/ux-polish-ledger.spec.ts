import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const centralEvidence = "C:/Users/josna/OneDrive/Desktop/Claude Projects/Tilo/agy-bridge/evidence";
const localEvidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "UX-POLISH",
);

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`UX-POLISH-LEDGER ${width} ${theme} has polished controls and no overlap`, async ({
      page,
    }) => {
      const dirs = [
        localEvidence,
        resolve(localEvidence, "../UX-POLISH-LEDGER"),
        resolve(centralEvidence, "UX-POLISH"),
        resolve(centralEvidence, "UX-POLISH-LEDGER"),
      ];
      for (const dir of dirs) {
        mkdirSync(dir, { recursive: true });
      }

      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/ledger");
      await expect(page.getByRole("heading", { name: "Ledger", exact: true })).toBeVisible({
        timeout: 15_000,
      });

      if (theme === "dark") {
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      }
      await page.evaluate(() => document.fonts.ready.then(() => undefined));

      const audit = await page.evaluate(() => {
        const links = [
          ...document.querySelectorAll<HTMLAnchorElement>(".park-ledger-root a"),
        ].filter((link) => link.offsetParent !== null);
        const unnamedIconButtons = [
          ...document.querySelectorAll<HTMLButtonElement>(".park-ledger-root button"),
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

      const shotName = `${width}-${theme}-Ledger.png`;
      for (const dir of dirs) {
        await page.screenshot({
          path: resolve(dir, shotName),
          fullPage: true,
          animations: "disabled",
        });
      }
    });
  }
}
