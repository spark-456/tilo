// WEB-3a acceptance (plan sections 1 and 10; README "Routes", "The `app` prop", "Focus"): the Park app
// skeleton in a real browser at 1440x900 and 390x844. /park/<page> renders the page registry's placeholder
// for each of the nine pages inside one [data-park] root; an unknown /park path shows the Park not-found
// page; history back and forward switch pages without a reload; the old app is untouched at / and
// /worlds; the park chunk is not fetched by a landing visit (NFR-01).
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-shell.spec.ts --project=chromium --no-deps --workers=3
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";
import { DESKTOP, MOBILE } from "./support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;

const ROUTES = [
  ["/park/home", "home", "Home"],
  ["/park/worlds", "worlds", "Worlds"],
  ["/park/world/k1", "world", "World"],
  ["/park/skills", "skills", "Skills"],
  ["/park/ledger", "ledger", "Ledger"],
  ["/park/agenda", "agenda", "Agenda"],
  ["/park/team", "team", "Team"],
  ["/park/profile", "profile", "Profile"],
  ["/park/connectors", "connectors", "Connectors"],
] as const;

const RING = {
  outlineStyle: "solid",
  outlineWidth: "3px",
  outlineColor: "rgb(90, 63, 224)",
  outlineOffset: "2px",
};

const markDocument = (page: Page) =>
  page.evaluate(() => {
    Reflect.set(window, "__shellMarker", "same document");
  });
const marker = (page: Page) => page.evaluate(() => Reflect.get(window, "__shellMarker"));

// A cold Vite dev server optimises its dependencies on the first request and reloads the page; warm it
// once per worker so no test pays for it.
test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(150_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/park/home", { timeout: 120_000 });
  await page
    .getByTestId("park-page-home")
    .waitFor({ timeout: 120_000 })
    .catch(() => undefined);
  await page.close();
});

for (const [name, viewport] of Object.entries(SIZES)) {
  test.describe(`park shell at ${name}`, () => {
    test.use({ viewport });

    test(`WEB_3a_e2e_${name}_park_home_renders_the_root_and_the_placeholder_with_no_console_errors`, async ({
      page,
    }) => {
      const problems = collectConsoleProblems(page);
      await page.goto("/park/home");
      await expect(page.locator("[data-park]")).toHaveCount(1);
      await expect(page.locator("[data-park]")).toHaveAttribute("data-time", "day");
      await expect(page.getByTestId("park-page-home")).toBeVisible();
      await expect(page.getByTestId("park-page-home")).toContainText("Not built yet");
      await expect(page.getByRole("main")).toHaveCount(1);
      expect(problems).toEqual([]);
    });

    for (const [path, id, label] of ROUTES) {
      test(`WEB_3a_e2e_${name}_${path}_renders_the_${id}_placeholder`, async ({ page }) => {
        const problems = collectConsoleProblems(page);
        await page.goto(path);
        await expect(page.getByTestId(`park-page-${id}`)).toBeVisible();
        await expect(page.getByRole("heading", { level: 1 })).toHaveText(label);
        await expect(page.locator('[data-testid^="park-page-"]')).toHaveCount(1);
        await expect(page.getByRole("main")).toHaveCount(1);
        await expect(page).toHaveTitle(`${label} · Tilo`);
        expect(problems).toEqual([]);
      });
    }

    test(`WEB_3a_e2e_${name}_a_world_route_shows_its_id`, async ({ page }) => {
      await page.goto("/park/world/k1");
      await expect(page.getByTestId("park-page-world")).toContainText("k1");
    });

    test(`WEB_3a_e2e_${name}_/park_is_home_and_unknown_params_are_ignored`, async ({ page }) => {
      await page.goto("/park");
      await expect(page.getByTestId("park-page-home")).toBeVisible();
      await page.goto("/park/home?x=1");
      await expect(page.getByTestId("park-page-home")).toBeVisible();
      await expect(page.getByTestId("park-page-home")).not.toContainText("x=1");
    });

    test(`WEB_3a_e2e_${name}_an_unknown_park_path_shows_the_not_found_page`, async ({ page }) => {
      const problems = collectConsoleProblems(page);
      await page.goto("/park/nope");
      await expect(page.getByTestId("park-not-found")).toBeVisible();
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Page not found");
      await expect(page.getByRole("link", { name: /home/i })).toHaveAttribute("href", "/park/home");
      await expect(page.locator('[data-testid^="park-page-"]')).toHaveCount(0);
      await expect(page).toHaveTitle("Page not found · Tilo");
      expect(problems).toEqual([]);
    });

    test(`WEB_3a_e2e_${name}_the_not_found_link_goes_home_and_back_returns`, async ({ page }) => {
      await page.goto("/park/nope");
      await markDocument(page);
      await page.getByTestId("park-not-found").getByRole("link").click();
      await expect(page.getByTestId("park-page-home")).toBeVisible();
      expect(page.url()).toMatch(/\/park\/home$/);
      expect(await marker(page), "no page load happened").toBe("same document");
      await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
      await page.goBack();
      await expect(page.getByTestId("park-not-found")).toBeVisible();
      await page.goForward();
      await expect(page.getByTestId("park-page-home")).toBeVisible();
      expect(await marker(page)).toBe("same document");
    });

    test(`WEB_3a_e2e_${name}_browser_back_and_forward_switch_pages`, async ({ page }) => {
      await page.goto("/park/home");
      await markDocument(page);
      await page.evaluate(() => {
        window.history.pushState({}, "", "/park/ledger");
        window.dispatchEvent(new PopStateEvent("popstate"));
      });
      await expect(page.getByTestId("park-page-ledger")).toBeVisible();
      await expect(page).toHaveTitle("Ledger · Tilo");
      await page.evaluate(() => {
        window.history.pushState({}, "", "/park/team?focus=share");
        window.dispatchEvent(new PopStateEvent("popstate"));
      });
      await expect(page.getByTestId("park-page-team")).toBeVisible();
      await page.goBack();
      await expect(page.getByTestId("park-page-ledger")).toBeVisible();
      await page.goBack();
      await expect(page.getByTestId("park-page-home")).toBeVisible();
      await page.goForward();
      await expect(page.getByTestId("park-page-ledger")).toBeVisible();
      expect(await marker(page), "back and forward stayed in one document").toBe("same document");
    });

    test(`WEB_3a_e2e_${name}_Tab_reaches_the_not_found_link_with_the_focus_ring`, async ({
      page,
    }) => {
      await page.goto("/park/nope");
      const link = page.getByTestId("park-not-found").getByRole("link");
      for (let i = 0; i < 4; i++) {
        await page.keyboard.press("Tab");
        if (await link.evaluate((el) => el === document.activeElement)) break;
      }
      await expect(link).toBeFocused();
      const style = await link.evaluate((el) => {
        const s = getComputedStyle(el);
        return {
          outlineStyle: s.outlineStyle,
          outlineWidth: s.outlineWidth,
          outlineColor: s.outlineColor,
          outlineOffset: s.outlineOffset,
        };
      });
      expect(style).toEqual(RING);
    });

    test(`WEB_3a_e2e_${name}_axe_finds_nothing_serious_on_the_placeholders_and_not_found`, async ({
      page,
    }) => {
      test.setTimeout(150_000); // ten pages, each scanned by axe
      for (const path of [...ROUTES.map((r) => r[0]), "/park/nope"]) {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
          .analyze();
        const bad = results.violations.filter(
          (v) => v.impact === "serious" || v.impact === "critical",
        );
        expect(bad, `${path}: ${JSON.stringify(bad, null, 2)}`).toEqual([]);
      }
    });

    test(`WEB_3a_e2e_${name}_the_page_does_not_scroll_sideways`, async ({ page }) => {
      await page.goto("/park/home");
      await expect(page.getByTestId("park-page-home")).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    });
  });
}

test.describe("the old app and the landing bundle", () => {
  test.use({ viewport: DESKTOP });

  test("WEB_3a_e2e_slash_still_renders_the_old_app", async ({ page }) => {
    const problems = collectConsoleProblems(page);
    await page.goto("/");
    await expect(page.getByTestId("stage-frame")).toBeVisible();
    await expect(page.locator("[data-park]")).toHaveCount(0);
    expect(problems).toEqual([]);
  });

  test("WEB_3a_e2e_worlds_still_renders_the_old_screen", async ({ page }) => {
    await page.goto("/worlds");
    await expect(page.getByTestId("screen-page")).toBeVisible();
    await expect(page.getByTestId("top-bar")).toBeVisible();
    await expect(page.locator("[data-park]")).toHaveCount(0);
  });

  test("WEB_3a_e2e_a_landing_visit_does_not_fetch_the_park_app_chunk", async ({ page }) => {
    const parkModules: string[] = [];
    page.on("request", (r) => {
      if (/\/src\/park\/app\/(ParkApp|context|pages|store)/.test(r.url()))
        parkModules.push(r.url());
    });
    await page.goto("/");
    await expect(page.getByTestId("stage-frame")).toBeVisible();
    expect(parkModules, "NFR-01: the park chunk loads only under /park").toEqual([]);
    await page.goto("/park/home");
    await expect(page.getByTestId("park-page-home")).toBeVisible();
  });
});
