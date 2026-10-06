// WEB-5 acceptance (plan sections 8a and 10; README "Worlds"; design "Tilo App Worlds.dc.html"): /park/worlds in
// a real browser at 1440x900 and 390x844. The three sections draw with the design's card heights (404, 196,
// 150), the status tabs, scale legend and search narrow the list, a decision is approved through the shell,
// and opening a world goes to /park/world/<id> without a page load. Any console error fails.
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park/worlds.spec.ts --project=chromium --no-deps --workers=3
import { type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "../support/console";
import { DESKTOP, MOBILE } from "../support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;
const HEIGHTS = { Cities: 404, Towns: 196, Villages: 150 } as const;

// A cold Vite dev server optimises its dependencies on the first request and reloads the page; warm it once.
test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(150_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/park/worlds", { timeout: 120_000 });
  await page
    .getByTestId("park-page-worlds")
    .waitFor({ timeout: 120_000 })
    .catch(() => undefined);
  await page.close();
});

const links = (page: Page, region: string) =>
  page.getByRole("region", { name: region }).getByRole("link");

for (const [name, viewport] of Object.entries(SIZES)) {
  test.describe(`worlds at ${name}`, () => {
    test.use({ viewport });

    test(`WEB_5_e2e_${name}_renders_three_sections_with_the_design_card_heights_and_no_console_errors`, async ({
      page,
    }) => {
      const problems = collectConsoleProblems(page);
      await page.goto("/park/worlds");
      await expect(page.getByTestId("park-page-worlds")).toBeVisible();
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Worlds");
      await expect(page).toHaveTitle("Worlds · Tilo");
      for (const [region, height] of Object.entries(HEIGHTS)) {
        const first = links(page, region).first();
        await expect(first).toBeVisible();
        expect((await first.boundingBox())?.height, region).toBe(height);
      }
      await expect(links(page, "Cities")).toHaveCount(3);
      await expect(links(page, "Towns")).toHaveCount(4);
      await expect(links(page, "Villages")).toHaveCount(4);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      if (name === "desktop") expect(overflow, "no horizontal page scroll").toBeLessThanOrEqual(0); // at 390 the design own grid minimum (330) decides
      expect(problems).toEqual([]);
    });

    test(`WEB_5_e2e_${name}_status_scale_and_search_narrow_the_list`, async ({ page }) => {
      const problems = collectConsoleProblems(page);
      await page.goto("/park/worlds");
      await expect(links(page, "Cities")).toHaveCount(3);
      await page.getByRole("tab", { name: /^Running/ }).click();
      await expect(page.getByRole("tab", { name: /^Running/ })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      await expect(links(page, "Cities")).toHaveCount(2);
      await expect(links(page, "Towns")).toHaveCount(1);
      await expect(page.getByRole("region", { name: "Villages" }).getByRole("link")).toHaveCount(2);
      await page.getByRole("button", { name: "Towns", exact: true }).click();
      await expect(page.getByRole("button", { name: "Towns", exact: true })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      await expect(page.getByRole("region", { name: "Cities" })).toHaveCount(0);
      await page.getByRole("button", { name: "All sizes", exact: true }).click();
      await page.getByRole("tab", { name: /^All/ }).click();
      await page.getByLabel("Search worlds").fill("INVOICE");
      await expect(page.getByRole("main").getByRole("link")).toHaveCount(1);
      await page.getByLabel("Search worlds").fill("zzz");
      await expect(page.getByText("No worlds match")).toBeVisible();
      expect(problems).toEqual([]);
    });

    test(`WEB_5_e2e_${name}_approving_a_decision_updates_the_card_and_the_count`, async ({
      page,
    }) => {
      const problems = collectConsoleProblems(page);
      await page.goto("/park/worlds");
      await expect(page.getByText("WAITING FOR YOU")).toBeVisible();
      await expect(page.getByText("2 buildings paused")).toBeVisible();
      await page.getByRole("button", { name: "Approve £3,420" }).click();
      await expect(page.getByText("Approved · just now")).toBeVisible();
      await expect(page.getByText("1 building paused")).toBeVisible();
      await expect(
        page
          .getByRole("link", { name: /K1 electric scooter/ })
          .getByText("1 decision", { exact: true }),
      ).toBeVisible();
      expect(problems).toEqual([]);
    });

    test(`WEB_5_e2e_${name}_opening_a_world_goes_to_its_route_without_a_page_load`, async ({
      page,
    }) => {
      await page.goto("/park/worlds");
      await expect(links(page, "Towns")).toHaveCount(4);
      await page.evaluate(() => Reflect.set(window, "__worldsMarker", "same document"));
      await page.locator('a[href="/park/world/northline"]').click();
      await expect(page).toHaveURL(/\/park\/world\/northline$/);
      await expect(page.getByTestId("park-page-world")).toBeVisible();
      expect(await page.evaluate(() => Reflect.get(window, "__worldsMarker"))).toBe(
        "same document",
      );
      await page.goBack();
      await expect(page.getByTestId("park-page-worlds")).toBeVisible();
    });
  });
}
