// ONBOARD-1 (user-requested, no PRD requirement; BQ-ONBOARD-1): the first-run welcome and the guided tour in a real
// browser, over the real Park nav. Automated browsers do not get the welcome by themselves, so every visit here asks
// for it with ?onboarding=1. Run on a private port:
// TILO_WEB_PORT=5191 pnpm --filter @tilo/web exec playwright test e2e/onboarding.spec.ts --project=chromium --no-deps --workers=1
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";
import { DESKTOP, MOBILE } from "./support/viewports";

const SHOTS = process.env.ONB_SHOTS;
const shot = async (page: Page, name: string) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};

const dialog = (page: Page) => page.getByRole("dialog");
const TITLES = [
  "Describe the work",
  "Worlds",
  "Skills",
  "Ledger",
  "Agenda",
  "Team",
  "Notifications",
  "Account menu",
];
const focusInDialog = (page: Page) =>
  page.evaluate(() => document.activeElement?.closest('[role="dialog"]') !== null);

// A cold Vite dev server optimises its dependencies on the first request and reloads the page; warm it once.
test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(150_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/", { timeout: 120_000 });
  await page
    .getByTestId("park-page-home")
    .waitFor({ timeout: 120_000 })
    .catch(() => undefined);
  await page.close();
});

for (const [name, viewport] of Object.entries({ desktop: DESKTOP, mobile: MOBILE })) {
  test.describe(`onboarding at ${name}`, () => {
    test.use({ viewport });

    test(`ONBOARD_1_e2e_welcome_tour_skip_replay_${name}`, async ({ page }) => {
      const problems = collectConsoleProblems(page);
      await page.goto("/?onboarding=1");
      const welcome = dialog(page);
      await expect(welcome).toBeVisible();
      await expect(welcome).toHaveAccessibleName("Welcome to Tilo");
      expect(await focusInDialog(page)).toBe(true);
      await shot(page, `${name}-1-welcome`);
      const axe = await new AxeBuilder({ page }).include('[role="dialog"]').analyze();
      expect(axe.violations.map((v) => v.id)).toEqual([]);

      await welcome.getByRole("button", { name: "Take the tour" }).click();
      const tour = dialog(page);
      for (const [i, title] of TITLES.entries()) {
        await expect(tour).toHaveAccessibleName(title);
        await expect(tour).toContainText(`Step ${i + 1} of ${TITLES.length}`);
        await expect(page.getByRole("status").filter({ hasText: `Step ${i + 1} of` })).toHaveText(
          `Step ${i + 1} of ${TITLES.length}: ${title}`,
        );
        if (i === 0 || i === 7) await shot(page, `${name}-2-step-${i + 1}`);
        if (i === 1) {
          const target = page.locator('nav[aria-label="Main"] a[href="/worlds"]');
          await expect(target).toHaveAttribute("aria-describedby", /onb-body/);
          const [r, t] = [await page.locator(".onb-ring").boundingBox(), await target.boundingBox()];
          expect(Math.abs((r?.x ?? 0) - ((t?.x ?? 0) - 4))).toBeLessThan(2);
          const axeStep = await new AxeBuilder({ page }).include('[role="dialog"]').analyze();
          expect(axeStep.violations.map((v) => v.id)).toEqual([]);
        }
        if (i < TITLES.length - 1) await tour.getByRole("button", { name: "Next" }).click();
      }
      // Esc ends the tour; nothing is left on the nav.
      await page.keyboard.press("Escape");
      await expect(dialog(page)).toHaveCount(0);
      expect(await page.locator('[aria-describedby*="onb-"]').count()).toBe(0);

      // Once per person: a reload does not show the welcome again.
      await page.reload();
      await expect(page.getByTestId("park-page-home")).toBeVisible();
      await expect(dialog(page)).toHaveCount(0);

      // Replay from the account menu.
      await page.getByRole("button", { name: "Account menu" }).click();
      await page.getByRole("menuitem", { name: /Take the tour/ }).click();
      await expect(dialog(page)).toHaveAccessibleName("Describe the work");
      expect(await focusInDialog(page)).toBe(true);
      await shot(page, `${name}-3-replay`);
      await page.keyboard.press("Tab");
      await page.keyboard.press("ArrowRight");
      await expect(dialog(page)).toHaveAccessibleName("Worlds");
      await page.keyboard.press("ArrowLeft");
      await expect(dialog(page)).toHaveAccessibleName("Describe the work");
      await dialog(page).getByRole("button", { name: "Skip tour" }).click();
      await expect(dialog(page)).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Account menu" })).toBeFocused();
      expect(problems).toEqual([]);
    });
  });
}

test("ONBOARD_1_e2e_reduced_motion_and_blocked_storage_still_work", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new Error("blocked");
      },
    });
  });
  await page.goto("/?onboarding=1");
  await expect(dialog(page)).toBeVisible();
  // Nothing moves: no transition or animation on the dialog.
  const motion = await dialog(page).evaluate((el) => {
    const s = getComputedStyle(el);
    return [s.transitionDuration, s.animationName];
  });
  expect(motion).toEqual(["0s", "none"]);
  await page.keyboard.press("Escape");
  await expect(dialog(page)).toHaveCount(0);
});

test("ONBOARD_1_e2e_automated_browsers_see_no_welcome_unless_asked", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("park-page-home")).toBeVisible();
  await expect(dialog(page)).toHaveCount(0);
});
