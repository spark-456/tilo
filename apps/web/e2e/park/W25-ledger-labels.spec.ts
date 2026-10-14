import { expect, test } from "@playwright/test";
import { collectConsoleProblems } from "../support/console";

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
]) {
  for (const time of ["day", "night"]) {
    test(`W25_UI_10_Ledger_labels_clear_plot_${viewport.width}_${time}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.clock.install({ time: new Date("2026-10-14T06:00:00Z") });
      await page.addInitScript((value) => localStorage.setItem("tilo.time", value), time);
      const problems = collectConsoleProblems(page);
      await page.goto("/ledger");
      await expect(page.locator(".park-ledger-svg")).toBeVisible();
      await expect(page.locator(".park-ledger-bars")).toBeAttached();
      await expect(page.locator("[data-park]")).toHaveAttribute("data-time", time);
      const failures = await page.evaluate(() => {
        const failures: string[] = [];
        const overlap = (a: DOMRect, b: DOMRect) =>
          Math.min(a.right, b.right) > Math.max(a.left, b.left) + 0.5 &&
          Math.min(a.bottom, b.bottom) > Math.max(a.top, b.top) + 0.5;
        const plot = document.querySelector(".park-ledger-svg")?.getBoundingClientRect();
        if (!plot) return ["missing plot"];
        const labels = Array.from(
          document.querySelectorAll(".park-ledger-ylabel, .park-ledger-xlabel, .park-ledger-note"),
        );
        labels.forEach((label, i) => {
          const box = label.getBoundingClientRect();
          if (!box.width || !box.height) failures.push(`hidden ${label.textContent}`);
          if (overlap(box, plot)) failures.push(`plot overlaps ${label.textContent}`);
          for (const other of labels.slice(i + 1)) {
            if (overlap(box, other.getBoundingClientRect())) {
              failures.push(`${label.textContent} overlaps ${other.textContent}`);
            }
          }
        });
        // Other charts already keep their text in rows outside their graphical marks.
        for (const selector of [
          ".park-ledger-legendrow",
          ".park-ledger-runends",
          ".park-ledger-type",
          ".park-ledger-weeks",
          ".park-ledger-bars",
          ".park-ledger-colhead",
        ]) {
          for (const row of document.querySelectorAll(selector)) {
            const text = Array.from(row.children).filter((el) => el.textContent?.trim());
            text.forEach((label, i) => {
              for (const other of text.slice(i + 1)) {
                if (overlap(label.getBoundingClientRect(), other.getBoundingClientRect())) {
                  failures.push(`${selector}: ${label.textContent} overlaps ${other.textContent}`);
                }
              }
            });
          }
        }
        if (document.documentElement.scrollWidth > innerWidth) failures.push("horizontal overflow");
        return failures;
      });
      expect(failures).toEqual([]);
      expect(problems).toEqual([]);
    });
  }
}
