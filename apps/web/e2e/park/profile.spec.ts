// WEB-12 acceptance in a real browser: /profile (the route lands with WEB-3a, the page with WEB-12, so
// this fails until then) at 1440x900 and 390x844, day and night. The h1 (the user's name) is visible, every
// tab opens with ZERO console errors or warnings, nothing overflows the page sideways (the nav and the
// notification matrix scroll inside their cards), the key computed values match the design, the matrix
// switches are 40x24 with a 16px knob travel, and the Appearance cards flip the shell's theme through
// setPref. The shell's "Sample data" chip arrives in WEB-3b: this spec neither requires nor forbids it.
// Run on a private port, three workers (a cold Vite start can time out the first test):
//   TILO_WEB_PORT=5413 pnpm --filter @tilo/web exec playwright test e2e/profile.spec.ts --project=chromium --no-deps --workers=3
//
// Assumption to settle in WEB-3a (same as team.spec): the day/night toggle in the nav is the button whose
// accessible name mentions "day" or "night"; the theme is read back from data-time on the [data-park] root.
import { type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "../support/console";
import { DESKTOP, MOBILE } from "../support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;
const THEMES = ["day", "night"] as const;
type Theme = (typeof THEMES)[number];
const NAME = "Alex Morgan";
const TABS = ["Profile", "Notifications", "Appearance", "Security", "Plan and billing"] as const;

async function open(page: Page, theme: Theme, tab?: string): Promise<void> {
  await page.goto(tab ? `/profile?tab=${tab}` : "/profile");
  await expect(page.getByRole("heading", { level: 1, name: NAME, exact: true })).toBeVisible();
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

const nav = (page: Page) => page.getByRole("navigation", { name: "Settings" });
const tab = (page: Page, name: string) => nav(page).getByRole("button", { name, exact: true });

for (const [vpName, viewport] of Object.entries(SIZES)) {
  test.describe(`WEB_12 /profile at ${vpName}`, () => {
    test.use({ viewport });

    for (const theme of THEMES) {
      test(`WEB_12_e2e_${vpName}_${theme}_profile_heading_is_visible_and_every_tab_opens_with_no_console_error`, async ({
        page,
      }) => {
        const problems = collectConsoleProblems(page);
        await open(page, theme);
        for (const name of TABS) {
          await tab(page, name).click();
          await expect(tab(page, name)).toHaveAttribute("aria-current", "page");
          await expect(
            page.getByRole("heading", { level: 1, name: NAME, exact: true }),
          ).toBeVisible();
        }
        await page.waitForTimeout(400);
        expect(problems, problems.join("\n")).toEqual([]);
      });

      test(`WEB_12_e2e_${vpName}_${theme}_the_tabs_and_their_sections_are_on_the_page`, async ({
        page,
      }) => {
        await open(page, theme);
        await expect(nav(page).getByRole("button")).toHaveCount(5);
        await expect(page.getByRole("region", { name: "Profile" })).toBeVisible();
        for (const label of [
          "Full name",
          "Work email",
          "Job title",
          "Time zone",
          "Language",
          "Working hours",
        ]) {
          await expect(page.getByLabel(label, { exact: false }).first(), label).toBeVisible();
        }
        await tab(page, "Notifications").click();
        await expect(page.getByRole("switch")).toHaveCount(16);
        await tab(page, "Security").click();
        await expect(page.getByRole("button", { name: "Sign out", exact: true })).toHaveCount(2);
        await tab(page, "Plan and billing").click();
        await expect(page.getByRole("button", { name: "Download" })).toHaveCount(3);
      });
    }

    // The "Sample data" chip belongs to the shell header; the page itself holds none.
    test(`WEB_12_e2e_the_shell_sample_data_chip_is_visible_on_the_profile_page_${vpName}`, async ({
      page,
    }) => {
      await open(page, "day");
      await expect(
        page.locator("header").getByRole("button", { name: "Sample data" }),
      ).toBeVisible();
      await expect(
        page.getByTestId("park-page-profile").getByRole("button", { name: "Sample data" }),
      ).toHaveCount(0);
    });

    test(`WEB_12_e2e_${vpName}_params_tab_opens_that_tab_first`, async ({ page }) => {
      await open(page, "day", "notifications");
      await expect(tab(page, "Notifications")).toHaveAttribute("aria-current", "page");
      await expect(page.getByRole("region", { name: "Notifications" })).toBeVisible();
    });

    test(`WEB_12_e2e_${vpName}_sheet_title_and_layout_match_the_design`, async ({ page }) => {
      await open(page, "day");
      const sheet = await nav(page).evaluate((el) => {
        const s = getComputedStyle(el.closest(".park-sheet") as Element);
        return { gap: s.rowGap, padding: s.padding, radius: s.borderTopLeftRadius };
      });
      expect(sheet.gap).toBe("22px");
      expect(sheet.radius).toBe("28px");
      if (vpName === "desktop") expect(sheet.padding).toBe("28px 32px 36px");
      const h1 = await page
        .getByRole("heading", { level: 1, name: NAME, exact: true })
        .evaluate((el) => {
          const s = getComputedStyle(el);
          return { size: s.fontSize, weight: s.fontWeight, spacing: s.letterSpacing };
        });
      expect(h1).toEqual({ size: "34px", weight: "900", spacing: "-0.8px" });
      const layout = await nav(page).evaluate((el) => {
        const g = getComputedStyle(el.parentElement as Element);
        return {
          direction: getComputedStyle(el).flexDirection,
          columns: g.gridTemplateColumns.split(" ").length,
          first: g.gridTemplateColumns.split(" ")[0],
        };
      });
      if (vpName === "desktop") {
        expect(layout).toMatchObject({ direction: "column", columns: 2, first: "230px" });
      } else {
        expect(layout).toMatchObject({ direction: "row", columns: 1 });
      }
    });

    test(`WEB_12_e2e_${vpName}_the_open_tab_is_marked_with_the_row_on_colours`, async ({
      page,
    }) => {
      await open(page, "day");
      const probe = await page.evaluate(() => {
        const root = document.querySelector("[data-park]") as HTMLElement;
        const el = document.createElement("span");
        el.style.background = "var(--rowOn)";
        el.style.color = "var(--heroInk)";
        root.appendChild(el);
        const s = getComputedStyle(el);
        const out = { bg: s.backgroundColor, fg: s.color };
        el.remove();
        return out;
      });
      const open1 = await tab(page, "Profile").evaluate((el) => {
        const s = getComputedStyle(el);
        return { bg: s.backgroundColor, fg: s.color, h: s.height };
      });
      expect(open1).toEqual({ bg: probe.bg, fg: probe.fg, h: "42px" });
      const closed = await tab(page, "Security").evaluate(
        (el) => getComputedStyle(el).backgroundColor,
      );
      expect(closed).toMatch(/^rgba\(0, 0, 0, 0\)$|^transparent$/);
    });

    test(`WEB_12_e2e_${vpName}_no_tab_scrolls_the_page_sideways`, async ({ page }) => {
      await open(page, "day");
      for (const name of TABS) {
        await tab(page, name).click();
        const over = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(over, `${name}: no horizontal page scroll`).toBeLessThanOrEqual(1);
      }
    });

    test(`WEB_12_e2e_${vpName}_matrix_switches_are_40_by_24_knob_18_travel_16`, async ({
      page,
    }) => {
      await open(page, "day");
      await tab(page, "Notifications").click();
      const geometry = (name: string) =>
        page.getByRole("switch", { name, exact: true }).evaluate((el) => {
          const sw = el.getBoundingClientRect();
          const knob = (el.firstElementChild as Element).getBoundingClientRect();
          return {
            w: sw.width,
            h: sw.height,
            knob: knob.width,
            knobH: knob.height,
            left: knob.left - sw.left,
          };
        });
      const on = await geometry("A decision needs you by Phone");
      const off = await geometry("Spend goes over a limit by Slack");
      expect(on).toMatchObject({ w: 40, h: 24, knob: 18, knobH: 18, left: 19 });
      expect(off).toMatchObject({ w: 40, h: 24, knob: 18, knobH: 18, left: 3 });
      const quiet = await geometry("Quiet hours");
      expect(quiet).toMatchObject({ w: 44, h: 26, knob: 20, knobH: 20, left: 21 });
    });

    test(`WEB_12_e2e_${vpName}_appearance_cards_flip_the_theme_and_motion_stays_pressed`, async ({
      page,
    }) => {
      await open(page, "day");
      await tab(page, "Appearance").click();
      const card = page.getByRole("region", { name: "Appearance" });
      const root = page.locator("[data-park]").first();
      await card.getByText("Night", { exact: true }).click();
      await expect(root).toHaveAttribute("data-time", "night");
      await card.getByText("Day", { exact: true }).click();
      await expect(root).toHaveAttribute("data-time", "day");
      await card.getByText("Still", { exact: true }).click();
      await expect(
        card.getByText("Nothing moves. Best for older laptops and long sessions."),
      ).toBeVisible();
    });
  });
}
