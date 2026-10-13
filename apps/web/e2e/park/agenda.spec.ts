// WEB-9 acceptance in a real browser: the Park Agenda at /agenda, 1440x900 and 390x844. The page
// renders the designed copy on the fixture Api, the pinboard and calendar controls work, "Find a time"
// books a slot, "Review and approve" goes to the world through the shell (no reload), and nothing is
// written to the console.
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park/agenda.spec.ts --project=chromium --no-deps --workers=1
import { type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "../support/console";
import { DESKTOP, MOBILE } from "../support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;

// P0-08b W4: sample slots follow today. Pin the reference day, preserving real timers.
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date(2026, 8, 24, 12));
});

// A cold Vite dev server optimises its dependencies on the first request and reloads the page; warm it
// once per worker so no test pays for it.
test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(150_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/agenda", { timeout: 120_000 });
  await page
    .getByRole("heading", { level: 1, name: "Agenda" })
    .waitFor({ timeout: 120_000 })
    .catch(() => undefined);
  await page.close();
});

const open = async (page: Page) => {
  await page.goto("/agenda");
  await expect(page.getByRole("heading", { level: 1, name: "Agenda" })).toBeVisible();
};

for (const [name, viewport] of Object.entries(SIZES)) {
  test.describe(`park agenda at ${name}`, () => {
    test.use({ viewport });

    test(`WEB_9_e2e_${name}_renders_the_designed_page_with_one_primary_button_and_no_console_output`, async ({
      page,
    }) => {
      const problems = collectConsoleProblems(page);
      await open(page);
      await expect(page).toHaveTitle("Agenda · Tilo");
      await expect(page.getByTestId("park-page-agenda")).toHaveAttribute("data-source", "fixture");
      for (const name of ["Boards", "This week"])
        await expect(page.getByRole("region", { name })).toBeVisible();
      await expect(page.getByRole("complementary", { name: "Event detail" })).toContainText(
        "Supplier sync · Northline",
      );
      await expect(page.getByRole("button", { name: "Find a time" }).first()).toBeVisible();
      await expect(page.locator(".park-btn--primary")).toHaveCount(1);
      await expect(page.getByText("Sample data · no calendar sync recorded")).toBeVisible();
      expect(problems).toEqual([]);
    });

    test(`WEB_9_e2e_${name}_has_no_horizontal_scroll`, async ({ page }) => {
      await open(page);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    });

    test(`WEB_9_e2e_${name}_pins_can_be_added_checked_off_and_regrouped`, async ({ page }) => {
      const problems = collectConsoleProblems(page);
      await open(page);
      const team = page.locator('[data-board="team"]');
      await team.getByLabel("Pin to Team board").fill("Order name tags");
      await team.getByRole("button", { name: "Pin it" }).click();
      await expect(team).toContainText("Order name tags");
      await expect(team).toContainText("7 open");
      await page.locator('[data-pin="t3"]').getByRole("button", { name: "Mark as done" }).click();
      await expect(team).toContainText("6 open");
      await page.getByRole("radio", { name: "Grouped" }).click();
      await expect(team).toContainText("NEEDS SOMEONE");
      await expect(team.getByRole("button", { name: "Pin", exact: true })).toBeVisible();
      expect(problems).toEqual([]);
    });

    test(`WEB_9_e2e_${name}_find_a_time_books_a_slot_and_pins_it`, async ({ page }) => {
      const problems = collectConsoleProblems(page);
      await open(page);
      await page.getByRole("button", { name: "Find a time" }).first().click();
      await expect(
        page.getByText("Tilo checked all four calendars. Pick a dashed slot to book it."),
      ).toBeVisible();
      await page.locator("[data-slot]").first().click();
      await expect(page.getByRole("status")).toContainText(
        "Booked Thu 16:00 on your Agenda. Invites go out from Google Calendar once it's connected and you approve",
      );
      await expect(page.locator('[data-pin="tg"]')).toContainText("K1 gate review booked");
      await expect(page.locator("[data-slot]")).toHaveCount(0);
      expect(problems).toEqual([]);
    });

    test(`WEB_9_e2e_${name}_review_and_approve_opens_the_world_without_a_reload`, async ({
      page,
    }) => {
      await open(page);
      await page.evaluate(() => Reflect.set(window, "__marker", "same document"));
      await page
        .locator('[data-pin="t1"]')
        .getByRole("button", { name: "Review and approve" })
        .click();
      await expect(page).toHaveURL(/\/world\/k1$/);
      expect(await page.evaluate(() => Reflect.get(window, "__marker"))).toBe("same document");
    });
  });
}
