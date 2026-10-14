// WEB-3a acceptance (plan sections 1 and 10; README "Routes", "The `app` prop", "Focus"): the Park app
// skeleton in a real browser at 1440x900 and 390x844. The root paths (/, /worlds, /world/<id>, ...) render the
// page registry's placeholder for each of the nine pages inside one [data-park] root (WEB-CUTOVER: /park/<page>
// stays an alias); an
// unknown /park path shows the Park not-found page; history back and forward switch pages without a reload;
// the old app is untouched at its kept paths (/more; the world lenses are Park since OLD-UI-OUT-2); a kept path never fetches the park
// chunk and the landing / loads the Park shell without the old app's stage engine (NFR-01).
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-shell.spec.ts --project=chromium --no-deps --workers=3
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { PLACEHOLDER_PAGES } from "../test-support/park/realPages";
import { collectConsoleProblems } from "./support/console";
import { DESKTOP, MOBILE } from "./support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;

const ROUTES = (
  [
    ["/", "home", "Home"],
    ["/worlds", "worlds", "Worlds"],
    ["/world/k1", "world", "World"],
    ["/skills", "skills", "Skills"],
    ["/ledger", "ledger", "Ledger"],
    ["/agenda", "agenda", "Agenda"],
    ["/team", "team", "Team"],
    ["/profile", "profile", "Profile"],
    ["/connectors", "connectors", "Connectors"],
  ] as const
).filter(([, id]) => PLACEHOLDER_PAGES.includes(id)); // a real page has its own spec

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
  await page.goto("/", { timeout: 120_000 });
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
      await page.goto("/");
      await expect(page.locator("[data-park]")).toHaveCount(1);
      await expect(page.locator("[data-park]")).toHaveAttribute("data-time", "day");
      await expect(page.getByTestId("park-page-home")).toBeVisible();
      if (PLACEHOLDER_PAGES.includes("home")) {
        await expect(page.getByTestId("park-page-home")).toContainText("Not built yet");
      }
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

    test(`WEB_3a_e2e_${name}_the_design_fonts_are_declared_on_park_pages`, async ({ page }) => {
      await page.goto("/");
      // The faces are declared by the lazy park chunk's CSS: wait for the page, then poll the list.
      await expect(page.getByRole("main")).toBeVisible();
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      // The design: Nunito 800 and 900 (display, logo) and Nunito Sans 400, 600, 700 and 800 (all UI text).
      const wanted = [
        "Nunito 800",
        "Nunito 900",
        "Nunito Sans 400",
        "Nunito Sans 600",
        "Nunito Sans 700",
        "Nunito Sans 800",
      ];
      await expect
        .poll(
          async () => {
            const faces = await page.evaluate(() =>
              [...document.fonts].map((f) => `${f.family.replace(/"/g, "")} ${f.weight}`),
            );
            return wanted.filter((face) => !faces.includes(face));
          },
          { message: "design faces still missing" },
        )
        .toEqual([]);
    });

    test(`WEB_3a_e2e_${name}_a_world_route_shows_its_id`, async ({ page }) => {
      await page.goto("/world/k1");
      await expect(page.getByTestId("park-page-world")).toHaveAttribute("data-world-id", "k1");
    });

    test(`WEB_3a_e2e_${name}_slash_and_the_park_alias_are_home_and_unknown_params_are_ignored`, async ({
      page,
    }) => {
      await page.goto("/park");
      await expect(page.getByTestId("park-page-home")).toBeVisible();
      await page.goto("/park/home?x=1");
      await expect(page.getByTestId("park-page-home")).toBeVisible();
      await page.goto("/?x=1");
      await expect(page.getByTestId("park-page-home")).toBeVisible();
      await expect(page.getByTestId("park-page-home")).not.toContainText("x=1");
    });

    test(`WEB_3a_e2e_${name}_an_unknown_park_path_shows_the_not_found_page`, async ({ page }) => {
      const problems = collectConsoleProblems(page);
      await page.goto("/park/nope");
      await expect(page.getByTestId("park-not-found")).toBeVisible();
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Page not found");
      // WEB-3b: the nav has two more Home links, so the not-found page's own link is found inside it.
      await expect(
        page.getByTestId("park-not-found").getByRole("link", { name: /home/i }),
      ).toHaveAttribute("href", "/");
      await expect(page.locator('[data-testid^="park-page-"]')).toHaveCount(0);
      await expect(page).toHaveTitle("Page not found · Tilo");
      expect(problems).toEqual([]);
    });

    test(`WEB_3a_e2e_${name}_the_not_found_link_goes_home_and_back_returns`, async ({ page }) => {
      await page.goto("/park/nope");
      await markDocument(page);
      await page.getByTestId("park-not-found").getByRole("link").click();
      await expect(page.getByTestId("park-page-home")).toBeVisible();
      expect(new URL(page.url()).pathname).toBe("/");
      expect(await marker(page), "no page load happened").toBe("same document");
      await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
      await page.goBack();
      await expect(page.getByTestId("park-not-found")).toBeVisible();
      await page.goForward();
      await expect(page.getByTestId("park-page-home")).toBeVisible();
      expect(await marker(page)).toBe("same document");
    });

    test(`WEB_3a_e2e_${name}_browser_back_and_forward_switch_pages`, async ({ page }) => {
      await page.goto("/");
      await markDocument(page);
      await page.evaluate(() => {
        window.history.pushState({}, "", "/ledger");
        window.dispatchEvent(new PopStateEvent("popstate"));
      });
      await expect(page.getByTestId("park-page-ledger")).toBeVisible();
      await expect(page).toHaveTitle("Ledger · Tilo");
      await page.evaluate(() => {
        window.history.pushState({}, "", "/team?focus=share");
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
      // WEB-3b: the nav comes first in the tab order (logo, six tabs, chip, three buttons), then the page.
      for (let i = 0; i < 20; i++) {
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
        const axe = new AxeBuilder({ page }).withTags([
          "wcag2a",
          "wcag2aa",
          "wcag21aa",
          "wcag22aa",
        ]);
        // Design-owned exception (plan 8c): the reference's own invalid-email state dims the Team page's
        // Invite button to opacity .6 over --hero (2.89:1). Excluded on /team only, for that button only.
        if (path === "/team") axe.exclude(".park-team-invite");
        const results = await axe.analyze();
        const bad = results.violations.filter(
          (v) => v.impact === "serious" || v.impact === "critical",
        );
        expect(bad, `${path}: ${JSON.stringify(bad, null, 2)}`).toEqual([]);
      }
    });

    test(`WEB_3a_e2e_${name}_the_page_does_not_scroll_sideways`, async ({ page }) => {
      await page.goto("/");
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

  const PARK_CHUNK = /\/src\/park\/app\/(ParkApp|context|pages|store)/;

  test("WEB_3a_e2e_slash_and_worlds_are_the_park_app_now", async ({ page }) => {
    const problems = collectConsoleProblems(page);
    await page.goto("/");
    await expect(page.getByTestId("park-page-home")).toBeVisible();
    await expect(page.locator("[data-park]")).toHaveCount(1);
    await expect(page.getByTestId("stage-frame")).toHaveCount(0);
    await page.goto("/worlds");
    await expect(page.getByTestId("park-page-worlds")).toBeVisible();
    await expect(page.getByTestId("screen-page")).toHaveCount(0);
    expect(problems).toEqual([]);
  });

  test("WEB_3a_e2e_the_old_app_is_untouched_at_more_and_the_stage_path_is_Park", async ({
    page,
  }) => {
    const problems = collectConsoleProblems(page);
    await page.goto("/more");
    await expect(page.getByTestId("screen-page")).toBeVisible();
    await expect(page.getByTestId("top-bar")).toBeVisible();
    await expect(page.locator("[data-park]")).toHaveCount(0);
    // OLD-UI-OUT-2: the world's lenses and Needs you are Park pages now.
    await page.goto("/world/w_village_basic/stage");
    await expect(page.getByTestId("stage-frame")).toBeVisible();
    await expect(page.locator("[data-park]")).toHaveCount(1);
    await expect(page.getByTestId("screen-page")).toHaveCount(0);
    expect(problems).toEqual([]);
  });

  test("WEB_3a_e2e_a_kept_old_app_path_does_not_fetch_the_park_app_chunk", async ({ page }) => {
    const parkModules: string[] = [];
    page.on("request", (r) => {
      if (PARK_CHUNK.test(r.url())) parkModules.push(r.url());
    });
    await page.goto("/more");
    await expect(page.getByTestId("screen-page")).toBeVisible();
    expect(parkModules, "NFR-01: the park chunk loads only on a Park path").toEqual([]);
    await page.goto("/");
    await expect(page.getByTestId("park-page-home")).toBeVisible();
  });

  test("WEB_3a_e2e_the_landing_loads_the_park_shell_and_not_the_stage_engine", async ({ page }) => {
    const parkModules: string[] = [];
    const engine: string[] = [];
    page.on("request", (r) => {
      if (PARK_CHUNK.test(r.url())) parkModules.push(r.url());
      if (/pixi/i.test(r.url())) engine.push(r.url());
    });
    await page.goto("/");
    await expect(page.getByTestId("park-page-home")).toBeVisible();
    expect(parkModules.length, "the landing is the Park app: its chunk loads").toBeGreaterThan(0);
    expect(engine, "NFR-01: no Pixi stage engine on the landing").toEqual([]);
  });
});
