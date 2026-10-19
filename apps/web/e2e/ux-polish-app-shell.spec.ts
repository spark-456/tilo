import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "UX-POLISH-APP-SHELL",
);

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`UX-POLISH-APP-SHELL ${width} ${theme} keeps navigation and notices readable`, async ({
      page,
    }) => {
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/");
      await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
      await expect(page.getByText("Sample data", { exact: true }).first()).toBeVisible();
      await expect(page.getByRole("button", { name: "Notifications" })).toBeVisible();
      await expect(page).toHaveTitle(/Tilo/);
      if (theme === "dark")
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: resolve(evidence, `${width}-${theme}-AppShell.png`),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}
