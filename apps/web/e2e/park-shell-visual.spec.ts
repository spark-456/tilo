// WEB-3b acceptance (plan sections 6.1, 8c, 8d; README "Shell", "Interactions and motion", "Responsive"): the
// visual shell of the Park City app in a real browser at 1440x900 and 390x844, day and night. Top nav
// geometry, the six tabs and the Worlds badge, the notifications popover (392) and account menu (300), the
// prototype sign-out toast, the day/night toggle and the static backdrop, the world loader (a real timer),
// the Sample data chip, console errors, axe (day) and sideways scroll.
//
// Not covered here: the Worlds badge dropping 2 -> 1 -> 0 as the two decisions are approved. Nothing in the
// shell approves a decision yet (the Home page is a placeholder and a dev-only hook is not allowed), so
// that is pinned by the store-driven unit tests (TopNav.test.tsx, "the badge follows the decisions").
//
// Motion is static in this ticket: nothing is asserted about animation (the restore is BQ-WEB-3).
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-shell-visual.spec.ts --project=chromium --no-deps --workers=3
import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";
import { DESKTOP, MOBILE } from "./support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;
const THEMES = ["day", "night"] as const;
type Theme = (typeof THEMES)[number];

// axe: design-owned contrast exceptions go here as `[selector, reason]` (the reference's own values win, as in
// park-components.spec.ts). None are known for the shell yet; the builder adds one only with its reason.
const AXE_EXCLUDE: readonly (readonly [string, string])[] = [];

const nav = (page: Page): Locator => page.locator("header.park-nav");
const root = (page: Page): Locator => page.locator("[data-park]");
const backdrop = (page: Page): Locator => page.getByTestId("park-backdrop");
const bell = (page: Page): Locator => page.getByRole("button", { name: "Notifications" });
const avatar = (page: Page): Locator => page.getByRole("button", { name: "Account menu" });
const loader = (page: Page): Locator => page.getByTestId("world-loader");

async function open(page: Page, path: string, theme: Theme = "day"): Promise<void> {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(nav(page)).toBeVisible();
  if (theme === "night") {
    await page.getByRole("button", { name: "Switch to night" }).click();
    await expect(root(page)).toHaveAttribute("data-time", "night");
  }
}

async function box(l: Locator) {
  const b = await l.boundingBox();
  if (!b) throw new Error("element has no box");
  return b;
}

// A cold Vite dev server optimises its dependencies on the first request and reloads the page; warm it
// once per worker so no test pays for it.
test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(150_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/park/home", { timeout: 120_000 });
  await page
    .locator("header.park-nav")
    .waitFor({ timeout: 120_000 })
    .catch(() => undefined);
  await page.close();
});

for (const [name, viewport] of Object.entries(SIZES)) {
  test.describe(`park shell at ${name}`, () => {
    test.use({ viewport });

    for (const theme of THEMES) {
      test(`WEB_3b_e2e_${name}_${theme}_nav_box_is_left_16_top_14_height_62_radius_22`, async ({
        page,
      }) => {
        await open(page, "/park/home", theme);
        const b = await box(nav(page));
        expect(b.x).toBeCloseTo(16, 0);
        expect(b.y).toBeCloseTo(14, 0);
        expect(b.height).toBeCloseTo(62, 0);
        expect(b.width).toBeCloseTo(viewport.width - 32, 0);
        const style = await nav(page).evaluate((el) => {
          const s = getComputedStyle(el);
          return { position: s.position, radius: s.borderTopLeftRadius, z: s.zIndex };
        });
        expect(style).toEqual({ position: "fixed", radius: "22px", z: "30" });
      });

      test(`WEB_3b_e2e_${name}_${theme}_six_tabs_with_home_current_and_the_worlds_badge_2`, async ({
        page,
      }) => {
        await open(page, "/park/home", theme);
        const tabs = nav(page).locator("nav[aria-label] a");
        await expect(tabs).toHaveCount(6);
        const labels = (await tabs.allTextContents()).map((t) => t.replace(/\d+$/, ""));
        expect(labels).toEqual(["Home", "Worlds", "Skills", "Ledger", "Agenda", "Team"]);
        await expect(tabs.nth(0)).toHaveAttribute("aria-current", "page");
        for (const i of [1, 2, 3, 4, 5]) await expect(tabs.nth(i)).not.toHaveAttribute("aria-current", /.*/);
        await expect(tabs.nth(1).locator(".park-nav__badge")).toHaveText("2");
        await expect(nav(page).locator(".park-nav__badge")).toHaveCount(1);
        const h = await box(tabs.nth(0));
        expect(h.height).toBeCloseTo(40, 0);
        const active = await tabs.nth(0).evaluate((el) => getComputedStyle(el).color);
        const idle = await tabs.nth(2).evaluate((el) => getComputedStyle(el).color);
        expect(active).not.toBe(idle); // heroInk against ink
      });

      test(`WEB_3b_e2e_${name}_${theme}_the_bell_opens_the_392_popover_and_Escape_closes_it`, async ({
        page,
      }) => {
        await open(page, "/park/home", theme);
        await expect(bell(page).locator(".park-nav__unread")).toHaveCount(1);
        await bell(page).focus();
        await bell(page).click();
        const pop = page.getByRole("dialog", { name: "Notifications" });
        await expect(pop).toBeVisible();
        const b = await box(pop);
        expect(b.y).toBeCloseTo(86, 0);
        if (viewport.width >= 600) {
          expect(b.width).toBeCloseTo(392, 0);
          expect(b.x + b.width).toBeCloseTo(viewport.width - 60, 0);
        } else {
          expect(b.width).toBeLessThanOrEqual(viewport.width - 32 + 0.5);
        }
        await expect(pop.getByRole("button")).toHaveCount(6); // Settings + five rows
        await expect(page.getByText("Laptop Depot needs budget sign-off")).toBeVisible();
        await expect(bell(page).locator(".park-nav__unread")).toHaveCount(0); // opening marks read
        await page.keyboard.press("Escape");
        await expect(pop).toHaveCount(0);
        await expect(bell(page)).toBeFocused();
      });

      test(`WEB_3b_e2e_${name}_${theme}_the_avatar_opens_the_300_menu_and_Sign_out_toasts`, async ({
        page,
      }) => {
        await open(page, "/park/home", theme);
        await avatar(page).click();
        const menu = page.getByRole("menu", { name: "Account" });
        await expect(menu).toBeVisible();
        const b = await box(menu);
        expect(b.width).toBeCloseTo(300, 0);
        expect(b.y).toBeCloseTo(86, 0);
        expect(b.x + b.width).toBeCloseTo(viewport.width - 16, 0);
        await expect(menu).toContainText("Alex Morgan");
        await expect(menu).toContainText("alex@northwind.co");
        await expect(menu).toContainText("Northwind Ops · Team plan");
        await expect(menu.getByRole("menuitem")).toHaveText([
          "Profile and settings",
          "Connectors6 on",
          "Team and roles",
          "Mobile appConcept",
          "Sign out",
        ]);
        await menu.getByRole("menuitem", { name: "Sign out" }).click();
        const toast = page.getByRole("status").filter({ hasText: "This is a prototype" });
        await expect(toast).toHaveText(/This is a prototype, so you stay signed in/);
        expect((await box(toast)).y).toBeCloseTo(92, 0);
        await expect(menu).toHaveCount(0);
        expect(page.url()).toMatch(/\/park\/home$/);
      });
    }

    test(`WEB_3b_e2e_${name}_account_menu_links_navigate_and_the_avatar_ring_shows`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      await avatar(page).click();
      await page.getByRole("menuitem", { name: /^Connectors/ }).click();
      await expect(page.getByTestId("park-page-connectors")).toBeVisible();
      expect(page.url()).toMatch(/\/park\/connectors$/);
      const ring = await avatar(page).evaluate((el) => getComputedStyle(el).boxShadow);
      expect(ring).toContain("rgb(90, 63, 224)"); // --hero on profile and connectors
      const home = nav(page).getByRole("link", { name: "Home" });
      await expect(home).not.toHaveAttribute("aria-current", /.*/);
    });

    test(`WEB_3b_e2e_${name}_tabs_navigate_without_a_reload_and_move_the_current_mark`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      await page.evaluate(() => {
        Reflect.set(window, "__marker", "same document");
      });
      await nav(page).getByRole("link", { name: "Skills" }).click();
      await expect(page.getByTestId("park-page-skills")).toBeVisible();
      await expect(nav(page).getByRole("link", { name: "Skills" })).toHaveAttribute("aria-current", "page");
      await expect(nav(page).getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current", /.*/);
      expect(await page.evaluate(() => Reflect.get(window, "__marker"))).toBe("same document");
      await page.goBack();
      await expect(page.getByTestId("park-page-home")).toBeVisible();
    });

    test(`WEB_3b_e2e_${name}_a_tab_can_be_reached_and_activated_from_the_keyboard`, async ({ page }) => {
      await open(page, "/park/home");
      const ledger = nav(page).getByRole("link", { name: "Ledger" });
      await ledger.focus();
      await expect(ledger).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("park-page-ledger")).toBeVisible();
    });

    test(`WEB_3b_e2e_${name}_the_toggle_flips_data_time_and_draws_a_different_city`, async ({ page }) => {
      await open(page, "/park/home");
      const before = await backdrop(page).evaluate((el) => el.innerHTML);
      await page.getByRole("button", { name: "Switch to night" }).click();
      await expect(root(page)).toHaveAttribute("data-time", "night");
      await expect(page.getByRole("button", { name: "Switch to day" })).toBeVisible();
      const night = await backdrop(page).evaluate((el) => el.innerHTML);
      expect(night).not.toBe(before);
      await page.getByRole("button", { name: "Switch to day" }).click();
      await expect(root(page)).toHaveAttribute("data-time", "day");
      expect(await backdrop(page).evaluate((el) => el.innerHTML)).toBe(before); // cached, the same city
    });

    test(`WEB_3b_e2e_${name}_the_backdrop_is_aria_hidden_full_bleed_not_clickable_and_veiled_off_home`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      await expect(backdrop(page)).toHaveCount(1);
      await expect(backdrop(page)).toHaveAttribute("aria-hidden", "true");
      const b = await box(backdrop(page));
      expect([b.x, b.y, b.width, b.height]).toEqual([0, 0, viewport.width, viewport.height]);
      const css = await backdrop(page).evaluate((el) => {
        const s = getComputedStyle(el);
        return { position: s.position, events: s.pointerEvents, z: s.zIndex };
      });
      expect(css).toEqual({ position: "fixed", events: "none", z: "0" });
      const hit = await page.evaluate(
        ([x, y]) => document.elementFromPoint(x ?? 0, y ?? 0)?.closest('[data-testid="park-backdrop"]') !== null,
        [viewport.width / 2, viewport.height / 2],
      );
      expect(hit, "a click at the centre must not land on the backdrop").toBe(false);
      await expect(backdrop(page).locator(".park-backdrop__veil")).toHaveCount(0);
      await page.goto("/park/ledger");
      await expect(backdrop(page).locator(".park-backdrop__veil")).toHaveCount(1);
      await expect(backdrop(page).locator(".park-backdrop__veil")).toBeVisible();
    });

    test(`WEB_3b_e2e_${name}_the_scene_is_scaled_by_the_larger_ratio_and_centred`, async ({ page }) => {
      await open(page, "/park/home");
      const scene = backdrop(page).locator(".park-backdrop__scene");
      const b = await box(scene);
      const s = Math.max(viewport.width / 1600, viewport.height / 1000);
      expect(b.width).toBeCloseTo(1600 * s, 0);
      expect(b.height).toBeCloseTo(1000 * s, 0);
      expect(b.x + b.width / 2).toBeCloseTo(viewport.width / 2, 0);
      expect(b.y + b.height / 2).toBeCloseTo(viewport.height / 2, 0);
    });

    test(`WEB_3b_e2e_${name}_a_village_opens_through_the_loader_then_the_page`, async ({ page }) => {
      await open(page, "/park/home");
      await bell(page).click();
      await page.getByRole("button", { name: /Competitor pricing is ready/ }).click();
      await expect(loader(page)).toBeVisible();
      await expect(loader(page)).toContainText("OPENING VILLAGE");
      await expect(loader(page)).toContainText("Competitor pricing");
      await expect(loader(page)).toContainText("Quick task · 1 agent");
      const card = await box(loader(page).locator(".park-wl__card"));
      expect(card.width).toBeCloseTo(Math.min(400, viewport.width - 48), 0);
      await expect(page.getByRole("dialog", { name: "Notifications" })).toHaveCount(0);
      await expect(page).toHaveURL(/\/park\/world\/comp$/, { timeout: 3000 });
      await expect(page.getByTestId("park-page-world")).toBeVisible({ timeout: 3000 });
      await expect(loader(page)).toHaveCount(0, { timeout: 3000 });
    });

    test(`WEB_3b_e2e_${name}_a_city_loader_says_OPENING_CITY_and_waits_for_step_3`, async ({ page }) => {
      await open(page, "/park/home");
      await bell(page).click();
      await page.getByRole("button", { name: /Laptop Depot needs budget sign-off/ }).click();
      await expect(loader(page)).toContainText("OPENING CITY");
      await expect(loader(page)).toContainText("K1 electric scooter");
      await expect(loader(page)).toContainText("Waking 38 agents");
      expect(page.url()).toMatch(/\/park\/home$/); // the old page stays until step 3 (about 1 s)
      await expect(page).toHaveURL(/\/park\/world\/k1$/, { timeout: 3000 });
      await expect(loader(page)).toHaveCount(0, { timeout: 3000 });
    });

    test(`WEB_3b_e2e_${name}_the_sample_data_chip_is_visible_and_explains_itself`, async ({ page }) => {
      await open(page, "/park/home");
      const chip = nav(page).getByRole("button", { name: "Sample data" });
      await expect(chip).toBeVisible();
      const b = await box(chip);
      expect(b.x).toBeGreaterThanOrEqual(0);
      expect(b.x + b.width).toBeLessThanOrEqual(viewport.width);
      await chip.click();
      await expect(
        page.getByText("Northwind Ops is a fictional team. Amounts are examples (£), dates are September 2026."),
      ).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog", { name: "Sample data" })).toHaveCount(0);
    });

    test(`WEB_3b_e2e_${name}_the_shell_logs_no_console_error_through_the_whole_tour`, async ({ page }) => {
      const problems = collectConsoleProblems(page);
      await open(page, "/park/home");
      await bell(page).click();
      await page.keyboard.press("Escape");
      await avatar(page).click();
      await page.getByRole("menuitem", { name: "Team and roles" }).click();
      await expect(page.getByTestId("park-page-team")).toBeVisible();
      await page.getByRole("button", { name: "Switch to night" }).click();
      await nav(page).getByRole("link", { name: "Worlds" }).click();
      await expect(page.getByTestId("park-page-worlds")).toBeVisible();
      await page.getByRole("button", { name: "Switch to day" }).click();
      expect(problems).toEqual([]);
    });

    test(`WEB_3b_e2e_${name}_day_axe_finds_nothing_serious_or_critical`, async ({ page }) => {
      test.setTimeout(90_000);
      for (const path of ["/park/home", "/park/ledger"]) {
        await open(page, path);
        let axe = new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]);
        for (const [selector] of AXE_EXCLUDE) axe = axe.exclude(selector);
        const results = await axe.analyze();
        const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
        expect(bad, `${path}: ${JSON.stringify(bad, null, 2)}`).toEqual([]);
      }
    });

    test(`WEB_3b_e2e_${name}_the_page_does_not_scroll_sideways_with_a_popover_open`, async ({ page }) => {
      for (const path of ["/park/home", "/park/ledger"]) {
        await open(page, path);
        await bell(page).click();
        const over = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(over, path).toBeLessThanOrEqual(0);
        await page.keyboard.press("Escape");
      }
    });
  });
}

test.describe("park shell at 390 wide", () => {
  test.use({ viewport: MOBILE });

  test("WEB_3b_e2e_mobile_the_tab_strip_scrolls_sideways_inside_the_nav", async ({ page }) => {
    await open(page, "/park/home");
    const strip = nav(page).locator("nav[aria-label]");
    const css = await strip.evaluate((el) => {
      const s = getComputedStyle(el);
      return { overflowX: s.overflowX, scroll: el.scrollWidth, client: el.clientWidth };
    });
    expect(css.overflowX).toBe("auto");
    expect(css.scroll).toBeGreaterThan(css.client); // six tabs do not fit in the strip at 390
    const bar = await box(nav(page));
    expect(bar.x + bar.width).toBeLessThanOrEqual(MOBILE.width - 16 + 0.5);
  });
});
