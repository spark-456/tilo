import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "@playwright/test";

const evidenceDirs = [
  resolve(process.cwd(), "../../agy-bridge/evidence/A11Y-390"),
  resolve(process.cwd(), "../../../../Tilo/agy-bridge/evidence/A11Y-390"),
];

for (const dir of evidenceDirs) {
  try {
    mkdirSync(dir, { recursive: true });
  } catch {}
}

const PAGES = [
  { name: "Home", path: "/" },
  { name: "Worlds", path: "/worlds" },
  { name: "Agenda", path: "/agenda" },
  { name: "Team", path: "/team" },
  { name: "Skills", path: "/skills" },
] as const;

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`A11Y-390 ${width} ${theme} screenshots`, async ({ page }) => {
      test.setTimeout(120_000);
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.addInitScript((val) => {
        sessionStorage.setItem("tilo-boot-seen", "1");
        localStorage.setItem("tilo.time", val === "dark" ? "night" : "day");
      }, theme);

      for (const p of PAGES) {
        await page.goto(p.path);
        if (theme === "dark") {
          await page
            .locator("[data-park]")
            .evaluate((node) => node.setAttribute("data-time", "night"));
        }
        await page.evaluate(() => document.fonts.ready.then(() => undefined));

        for (const dir of evidenceDirs) {
          await page.screenshot({
            path: resolve(dir, `${width}-${theme}-${p.name}.png`),
            fullPage: true,
            animations: "disabled",
          });
        }
      }
    });
  }
}
