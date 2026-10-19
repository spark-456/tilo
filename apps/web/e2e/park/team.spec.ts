// WEB-10 acceptance in a real browser: /team (the route lands with WEB-3a, so this fails until then) at
// 1440x900 and 390x844, day and night. The page heading is visible, the five members are on screen, the key computed values match the design, nothing overflows the page
// sideways (the 820px members table scrolls inside its card), and there are ZERO console errors or warnings.
// The shell's "Sample data" chip (WEB-3b nav) is asserted by the last test per viewport; the page itself
// renders no chip, which Team.static.test.ts pins.
// Run on a private port, three workers (a cold Vite start can time out the first test):
//   TILO_WEB_PORT=5411 pnpm --filter @tilo/web exec playwright test e2e/team.spec.ts --project=chromium --no-deps --workers=3
//
// Assumption to settle in WEB-3a: the day/night toggle is the nav button whose accessible name mentions
// "day" or "night"; the theme is read back from data-time on the [data-park] root (tokens/park.css).
import { type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "../support/console";
import { DESKTOP, MOBILE } from "../support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;
const THEMES = ["day", "night"] as const;
type Theme = (typeof THEMES)[number];
const MEMBERS = ["Alex Morgan", "Priya Shah", "Jin Park", "Tom Reyes", "Sam Ode"];

async function open(page: Page, theme: Theme): Promise<void> {
  await page.goto("/team");
  await expect(page.getByRole("heading", { level: 1, name: "Team", exact: true })).toBeVisible();
  const root = page.locator("[data-park]").first();
  const isNight = async (): Promise<boolean> => (await root.getAttribute("data-time")) === "night";
  if ((await isNight()) !== (theme === "night")) {
    await page
      .getByRole("button", { name: /day|night/i })
      .first()
      .click();
  }
  await expect.poll(isNight).toBe(theme === "night");
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
}

for (const [vpName, viewport] of Object.entries(SIZES)) {
  test.describe(`WEB_10 /team at ${vpName}`, () => {
    test.use({ viewport });

    for (const theme of THEMES) {
      test(`WEB_10_e2e_${vpName}_${theme}_team_heading_is_visible_with_no_console_error`, async ({
        page,
      }) => {
        const problems = collectConsoleProblems(page);
        await open(page, theme);
        await page.waitForTimeout(400);
        await expect(
          page.getByRole("heading", { level: 1, name: "Team", exact: true }),
        ).toBeVisible();
        expect(problems, problems.join("\n")).toEqual([]);
      });

      test(`WEB_10_e2e_${vpName}_${theme}_members_and_sections_are_on_the_page`, async ({
        page,
      }) => {
        await open(page, theme);
        const members = page.getByRole("region", { name: "Members" });
        for (const name of MEMBERS) {
          await expect(members.getByText(name, { exact: true }), name).toBeVisible();
        }
        for (const name of ["Approval coverage", "Approval rules", "What each role can do"]) {
          await expect(page.getByRole("region", { name })).toBeVisible();
        }
        await expect(page.getByRole("switch")).toHaveCount(5);
      });
    }

    test(`WEB_10_e2e_${vpName}_sheet_and_title_match_the_design`, async ({ page }) => {
      await open(page, "day");
      const sheet = await page.getByRole("region", { name: "Members" }).evaluate((el) => {
        const s = getComputedStyle(el.closest(".park-sheet") as Element);
        return { gap: s.rowGap, padding: s.padding, radius: s.borderTopLeftRadius };
      });
      expect(sheet.gap).toBe("22px");
      expect(sheet.radius).toBe("28px");
      if (vpName === "desktop") expect(sheet.padding).toBe("28px 32px 36px");
      const h1 = await page
        .getByRole("heading", { level: 1, name: "Team", exact: true })
        .evaluate((el) => {
          const s = getComputedStyle(el);
          return { size: s.fontSize, weight: s.fontWeight, spacing: s.letterSpacing };
        });
      expect(h1).toEqual({ size: "36px", weight: "900", spacing: "-0.8px" });
    });

    test(`WEB_10_e2e_${vpName}_page_does_not_scroll_sideways_and_the_table_scrolls_in_its_card`, async ({
      page,
    }) => {
      await open(page, "day");
      const over = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(over, "no horizontal page scroll").toBeLessThanOrEqual(1);
      const scroller = await page.getByRole("region", { name: "Members" }).evaluate((el) => {
        const hit = [...el.querySelectorAll("*")].find(
          (e) => getComputedStyle(e).overflowX === "auto" && e.scrollWidth >= 820,
        );
        return hit ? { scrolls: hit.scrollWidth > hit.clientWidth, width: hit.scrollWidth } : null;
      });
      expect(scroller, "an overflow-x:auto wrapper holds the 820px table").not.toBeNull();
      expect(scroller?.scrolls).toBe(vpName === "mobile");
    });

    // The chip belongs to the shell nav (WEB-3b), not to the page: the page renders none of its own.
    test(`WEB_10_e2e_${vpName}_shell_sample_data_chip_shows_on_the_team_page`, async ({ page }) => {
      await open(page, "day");
      await expect(
        page.locator("header").getByRole("button", { name: "Sample data" }),
      ).toBeVisible();
      await expect(
        page.getByTestId("park-page-team").getByRole("button", { name: "Sample data" }),
      ).toHaveCount(0);
    });
  });
}
