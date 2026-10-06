// WEB-11 acceptance in a real browser (plan section 10): /park/connectors at 1440x900 and 390x844, day and
// night. The heading is visible, the six fixture tiles are listed under Connected, and the console shows
// ZERO errors or warnings. The route lands with WEB-3a, so this fails until then (404 or the old app).
// Night is the shell's own `data-time="night"` on the `data-park` root, set after load.
// Run on a private port with three workers (a cold Vite start can time out the first test):
//   TILO_WEB_PORT=5412 pnpm --filter @tilo/web exec playwright test e2e/park/connectors.spec.ts --project=chromium --no-deps --workers=3
import { type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "../support/console";
import { DESKTOP, MOBILE } from "../support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;
const THEMES = ["day", "night"] as const;

async function openConnectors(page: Page, theme: (typeof THEMES)[number]): Promise<void> {
  await page.goto("/park/connectors");
  if (theme === "night") {
    await page.evaluate(() =>
      document.querySelector("[data-park]")?.setAttribute("data-time", "night"),
    );
  }
}

for (const [size, viewport] of Object.entries(SIZES)) {
  for (const theme of THEMES) {
    test.describe(`WEB_11_connectors_e2e ${size} ${theme}`, () => {
      test.use({ viewport });

      test(`WEB_11_connectors_e2e_heading_visible_and_zero_console_errors_${size}_${theme}`, async ({
        page,
      }) => {
        const problems = collectConsoleProblems(page);
        await openConnectors(page, theme);
        await expect(page.getByRole("heading", { level: 1, name: "Connectors" })).toBeVisible();
        await expect(page.locator("[data-park]").first()).toBeAttached();
        await expect(page.locator('[aria-label="Connected"] button')).toHaveCount(6);
        await expect(page.getByLabel("Search connectors")).toBeVisible();
        await page.waitForTimeout(500);
        expect(problems, problems.join("\n")).toEqual([]);
      });
    });
  }
}

for (const [size, viewport] of Object.entries(SIZES)) {
  test.describe(`WEB_11_connectors_e2e sample chip ${size}`, () => {
    test.use({ viewport });

    // The "Sample data" chip belongs to the shell header; the page itself holds none.
    test(`WEB_11_connectors_e2e_the_shell_sample_data_chip_is_visible_on_the_connectors_page_${size}`, async ({
      page,
    }) => {
      await openConnectors(page, "day");
      await expect(page.getByRole("heading", { level: 1, name: "Connectors" })).toBeVisible();
      await expect(
        page.locator("header").getByRole("button", { name: "Sample data" }),
      ).toBeVisible();
      await expect(
        page.getByTestId("park-page-connectors").getByRole("button", { name: "Sample data" }),
      ).toHaveCount(0);
    });
  });
}

test.describe("WEB_11_connectors_e2e drawer", () => {
  test.use({ viewport: DESKTOP });

  test("WEB_11_connectors_e2e_a_tile_opens_the_dialog_and_close_removes_it_with_no_console_error", async ({
    page,
  }) => {
    const problems = collectConsoleProblems(page);
    await openConnectors(page, "day");
    await expect(page.getByRole("heading", { level: 1, name: "Connectors" })).toBeVisible();
    await page.locator('[aria-label="Connected"] button', { hasText: "Gmail" }).click();
    const dialog = page.getByRole("dialog", { name: "Gmail" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("How far agents can go")).toBeVisible();
    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toHaveCount(0);
    expect(problems, problems.join("\n")).toEqual([]);
  });
});
