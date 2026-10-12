// FIRST-RUN / ONBOARD-1: per-page invitations replace the global automatic welcome.
// Existing keyboard, focus, anchor, dismissal, replay, contrast and reduced-motion properties stay pinned.
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";

const pages = [
  ["Home", "/", "Describe the work"],
  ["Worlds", "/worlds", "Choose a project"],
  ["World", "/world/k1", "Explore this project"],
  ["Agenda", "/agenda", "Plan your week"],
  ["Skills", "/skills", "Explore skills"],
  ["Ledger", "/ledger", "Review recorded costs"],
  ["Team", "/team", "See your team"],
  ["Connectors", "/connectors", "Check real connections"],
  ["Profile", "/profile", "Review your settings"],
] as const;
const dialog = (page: Page) => page.getByRole("dialog");
// A cold Vite server can re-optimise dependencies and reload once. Warm it before measuring invitations.
test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(150_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/", { timeout: 120_000 });
  await page.getByTestId("park-page-home").waitFor({ timeout: 120_000 });
  await page.close();
});
const shot = async (page: Page, name: string) => {
  if (process.env.ONB_SHOTS)
    await page.screenshot({ path: `${process.env.ONB_SHOTS}/${name}.png` });
};
const inView = async (page: Page) => {
  const box = await dialog(page).boundingBox();
  const viewport = page.viewportSize();
  if (!box || !viewport) throw new Error("Missing visible dialog or viewport");
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 1);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
};
for (const width of [1440, 390])
  for (const theme of ["day", "night"]) {
    test(`FIRST_RUN_FR_UX_13_all_pages_${width}_${theme}`, async ({ page }) => {
      test.setTimeout(180_000);
      const problems = collectConsoleProblems(page);
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.addInitScript((time) => localStorage.setItem("tilo.time", time), theme);
      for (const [name, route, contentTitle] of pages) {
        await page.goto(`${route}?onboarding=1`);
        await expect(page.getByTestId(`park-page-${name.toLowerCase()}`)).toBeVisible({
          timeout: 120_000,
        });
        await expect(dialog(page)).toHaveAccessibleName(`Take a tour of ${name}?`);
        await expect(page.locator(`[data-park][data-time="${theme}"]`)).toHaveCount(1);
        expect(
          await page.evaluate(() => document.activeElement?.closest('[role="dialog"]') !== null),
        ).toBe(true);
        await inView(page);
        await shot(page, `${width}-${theme}-${name}-invite`);
        if (name === "Home") {
          const result = await new AxeBuilder({ page }).include('[role="dialog"]').analyze();
          expect(result.violations.map((v) => v.id)).toEqual([]);
        }
        await dialog(page).getByRole("button", { name: "Not now" }).click();
        await expect(dialog(page)).toHaveCount(0);
        await page.reload();
        await expect(page.getByTestId(`park-page-${name.toLowerCase()}`)).toBeVisible();
        await expect(dialog(page)).toHaveCount(0);
        await page.getByRole("button", { name: "Account menu" }).click();
        await page.getByRole("menuitem", { name: /Take the tour/ }).click();
        await expect(dialog(page)).toHaveAccessibleName(name);
        await inView(page);
        await page.keyboard.press("ArrowRight");
        await expect(dialog(page)).toHaveAccessibleName(contentTitle);
        await expect(dialog(page)).toContainText("Step 2 of 3");
        await expect(
          page.locator('[aria-describedby*="onb-body"]:not([role="dialog"])'),
        ).toHaveCount(1);
        await inView(page);
        await shot(page, `${width}-${theme}-${name}-content`);
        await page.keyboard.press("ArrowLeft");
        await expect(dialog(page)).toHaveAccessibleName(name);
        await page.keyboard.press("ArrowRight");
        await page.keyboard.press("ArrowRight");
        await expect(dialog(page)).toHaveAccessibleName("Find help again");
        const [ring, target] = [
          await page.locator(".onb-ring").boundingBox(),
          await page.getByRole("button", { name: "Account menu" }).boundingBox(),
        ];
        if (!ring || !target) throw new Error("Missing help anchor or ring");
        expect(Math.abs(ring.x - (target.x - 4))).toBeLessThan(2);
        await inView(page);
        if (name === "Home") {
          const result = await new AxeBuilder({ page }).include('[role="dialog"]').analyze();
          expect(result.violations.map((v) => v.id)).toEqual([]);
        }
        await page.keyboard.press("Escape");
        await expect(dialog(page)).toHaveCount(0);
        await expect(page.getByRole("button", { name: "Account menu" })).toBeFocused();
        expect(await page.locator('[aria-describedby*="onb-"]').count()).toBe(0);
      }
      expect(problems).toEqual([]);
    });
  }
test("FIRST_RUN_ONBOARD_1_reduced_motion_blocked_storage_keyboard", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() =>
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new Error("blocked");
      },
    }),
  );
  await page.goto("/?onboarding=1");
  await expect(dialog(page)).toHaveAccessibleName("Take a tour of Home?");
  await dialog(page).getByRole("button", { name: "Not now" }).focus();
  await page.keyboard.press("Tab");
  await expect(dialog(page).getByRole("button", { name: "Take the tour" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog(page)).toHaveAccessibleName("Home");
  await dialog(page).getByRole("button", { name: "Skip tour" }).click();
  await expect(dialog(page)).toHaveCount(0);
});
