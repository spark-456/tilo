// WEB-3b acceptance (plan sections 6.1, 8a, 8c, 8d; README "Shell", "Interactions and motion", "Responsive",
// "Performance"): the visual shell of the Park City app in a real browser at 1440x900 and 390x844, day and
// night. Every number below was MEASURED on the reference (`design/Tilo App.dc.html` served over HTTP, in
// Chromium at the same two viewports), not read from the implementation: nav box, logo, tabs, badge, icon
// buttons, avatar ring, popover and menu boxes, tile colours, separator, toast, content column, loader card.
// Elements are found by role, label and text; where the reference gives an element no name the spec finds it
// by what it is (a 9px amber dot inside the bell, a 3px bar in the header, a 1px rule in the menu, a 16px
// ring), so any faithful markup passes.
//
// Not covered here: the Worlds badge dropping 2 -> 1 -> 0 as the two decisions are approved (nothing in the
// shell approves a decision yet and a dev-only hook is not allowed; the store-driven unit tests in Nav.test.tsx
// pin it), and the boot splash's numbers (it is on screen for a single frame once the engines are built;
// WorldLoader.test.tsx pins its copy and its removal). Motion is static in this ticket (BQ-WEB-3).
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-shell-visual.spec.ts --project=chromium --no-deps --workers=3
import { inflateSync } from "node:zlib";
import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";
import { DESKTOP, MOBILE } from "./support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;
const THEMES = ["day", "night"] as const;
type Theme = (typeof THEMES)[number];

// axe: a design-owned contrast exception goes here as [selector, reason] (the reference's own values win, as
// in park-components.spec.ts). None is known for the shell yet; the builder adds one only with its reason.
const AXE_EXCLUDE: readonly (readonly [string, string])[] = [];

const nav = (page: Page): Locator => page.locator("header");
const root = (page: Page): Locator => page.locator("[data-park]");
const bell = (page: Page): Locator => page.getByRole("button", { name: "Notifications" });
const avatar = (page: Page): Locator => page.getByRole("button", { name: "Account menu" });
const tab = (page: Page, name: string): Locator =>
  nav(page)
    .locator("nav a")
    .filter({ hasText: new RegExp(`^${name}\\d*$`) });
/** The scene's hidden layer: an aria-hidden element that holds the city's img or svg. */
const backdrop = (page: Page): Locator =>
  page
    .locator('body [aria-hidden="true"]')
    .filter({ has: page.locator("img, svg") })
    .first();
const loader = (page: Page): Locator =>
  page.getByRole("status").filter({ hasText: /OPENING (CITY|TOWN|VILLAGE)/ });

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
const style = (l: Locator, ...names: string[]) =>
  l.evaluate((el, props) => {
    const s = getComputedStyle(el);
    return Object.fromEntries(props.map((p) => [p, s.getPropertyValue(p)]));
  }, names);

/** RGB of one pixel of the page, read from a 1x1 screenshot (PNG decoded here, no image library). */
async function pixelAt(page: Page, x: number, y: number): Promise<number[]> {
  const png = await page.screenshot({ clip: { x, y, width: 1, height: 1 } });
  const idat: Buffer[] = [];
  for (let i = 8; i < png.length; ) {
    const len = png.readUInt32BE(i);
    if (png.toString("ascii", i + 4, i + 8) === "IDAT") idat.push(png.subarray(i + 8, i + 8 + len));
    i += 12 + len;
  }
  const raw = inflateSync(Buffer.concat(idat)); // one scanline: filter byte, then R G B (A)
  return [raw[1] ?? 0, raw[2] ?? 0, raw[3] ?? 0];
}

// A cold Vite dev server optimises its dependencies on the first request and reloads the page; warm it
// once per worker so no test pays for it.
test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(240_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/park/home", { timeout: 200_000 });
  await page
    .locator("header")
    .waitFor({ timeout: 200_000 })
    .catch(() => undefined);
  await page.close();
});

for (const [name, viewport] of Object.entries(SIZES)) {
  const wide = viewport.width >= 600;
  test.describe(`park shell at ${name}`, () => {
    test.use({ viewport });

    for (const theme of THEMES) {
      test(`WEB_3b_e2e_${name}_${theme}_nav_is_a_fixed_glass_bar_left_16_top_14_height_62_radius_22`, async ({
        page,
      }) => {
        await open(page, "/park/home", theme);
        const b = await box(nav(page));
        expect([b.x, b.y, b.height, b.width]).toEqual([16, 14, 62, viewport.width - 32]);
        const s = await style(
          nav(page),
          "position",
          "z-index",
          "border-top-left-radius",
          "backdrop-filter",
        );
        expect(s.position).toBe("fixed");
        expect(s["z-index"]).toBe("30");
        expect(s["border-top-left-radius"]).toBe("22px");
        expect(s["backdrop-filter"]).toContain("blur(20px)");
        if (theme === "day") {
          expect((await style(nav(page), "background-color"))["background-color"]).toBe(
            "rgba(255, 255, 255, 0.72)",
          );
        }
      });

      test(`WEB_3b_e2e_${name}_${theme}_six_tabs_home_current_h40_r14_15px_800_and_the_Worlds_badge_2`, async ({
        page,
      }) => {
        await open(page, "/park/home", theme);
        const tabs = nav(page).locator("nav a");
        const labels = (await tabs.allTextContents()).map((t) => t.replace(/\d+$/, ""));
        expect(labels).toEqual(["Home", "Worlds", "Skills", "Ledger", "Agenda", "Team"]);
        await expect(tab(page, "Home")).toHaveAttribute("aria-current", "page");
        for (const n of ["Worlds", "Skills", "Ledger", "Agenda", "Team"]) {
          await expect(tab(page, n)).not.toHaveAttribute("aria-current", /.*/);
        }
        const home = tab(page, "Home");
        const hb = await box(home);
        expect([hb.y, hb.height]).toEqual([25, 40]);
        expect(await style(home, "border-top-left-radius", "font-size", "font-weight")).toEqual({
          "border-top-left-radius": "14px",
          "font-size": "15px",
          "font-weight": "800",
        });
        if (theme === "day") {
          expect(await style(home, "color", "background-color")).toEqual({
            color: "rgb(74, 49, 204)",
            "background-color": "rgba(90, 63, 224, 0.1)",
          });
          expect((await style(tab(page, "Skills"), "color")).color).toBe("rgb(31, 29, 43)");
        }
        const badge = tab(page, "Worlds").locator("*").filter({ hasText: /^2$/ });
        await expect(badge).toHaveCount(1);
        const bb = await box(badge);
        expect(bb.height).toBe(20);
        expect(bb.width).toBeGreaterThanOrEqual(20);
        expect(await style(badge, "background-color", "color", "font-size", "font-weight")).toEqual(
          {
            "background-color": "rgb(240, 165, 0)",
            color: "rgb(31, 29, 43)",
            "font-size": "12px",
            "font-weight": "900",
          },
        );
        await expect(nav(page).getByText(/^[0-9]+$/)).toHaveCount(1); // no other badge
      });

      test(`WEB_3b_e2e_${name}_${theme}_logo_tile_34_visor_22x12_two_3px_dots_and_the_Nunito_900_wordmark`, async ({
        page,
      }) => {
        await open(page, "/park/home", theme);
        const logo = nav(page).getByRole("link", { name: "Tilo home" });
        const parts = await logo.evaluate((a) =>
          [...a.querySelectorAll("*")].map((e) => {
            const r = e.getBoundingClientRect();
            return [
              Math.round(r.width),
              Math.round(r.height),
              getComputedStyle(e).borderTopLeftRadius,
            ];
          }),
        );
        expect(parts).toContainEqual([34, 34, "12px"]);
        expect(parts).toContainEqual([22, 12, "5px"]);
        expect(parts.filter((p) => p[0] === 3 && p[1] === 3)).toHaveLength(2);
        const word = logo.getByText("tilo", { exact: true });
        const w = await style(word, "font-family", "font-size", "font-weight", "letter-spacing");
        expect(w["font-family"]).toMatch(/^"?Nunito"?(,|$)/);
        expect(w["font-size"]).toBe("27px");
        expect(w["font-weight"]).toBe("900");
        expect(w["letter-spacing"]).toBe("-0.5px");
        if (theme === "day") expect((await style(word, "color")).color).toBe("rgb(90, 63, 224)");
      });

      test(`WEB_3b_e2e_${name}_${theme}_icon_buttons_40_r13_avatar_38_with_the_line_ring_and_the_3px_bar`, async ({
        page,
      }) => {
        await open(page, "/park/home", theme);
        for (const n of [/Switch to/, "Notifications"]) {
          const b = nav(page).getByRole("button", { name: n });
          const r = await box(b);
          expect([r.y, r.width, r.height]).toEqual([25, 40, 40]);
          expect((await style(b, "border-top-left-radius"))["border-top-left-radius"]).toBe("13px");
        }
        const a = await box(avatar(page));
        expect([a.y, a.width, a.height]).toEqual([26, 38, 38]);
        expect(
          await style(avatar(page), "border-top-left-radius", "font-size", "font-weight"),
        ).toEqual({
          "border-top-left-radius": "999px",
          "font-size": "13px",
          "font-weight": "800",
        });
        if (theme === "day") {
          expect((await style(avatar(page), "box-shadow"))["box-shadow"]).toBe(
            "rgb(255, 255, 255) 0px 0px 0px 2px, rgba(31, 29, 43, 0.12) 0px 0px 0px 3.5px",
          );
        }
        // the progress bar: a 3px rounded strip on the bottom edge of the nav, 22px in from each side
        const bar = nav(page).locator(':scope > [aria-hidden="true"]');
        await expect(bar).toHaveCount(1);
        const bb = await box(bar);
        expect(bb.height).toBe(3);
        expect(bb.x).toBe(16 + 1 + 22);
        expect(bb.width).toBe(viewport.width - 32 - 2 - 44);
        expect(bb.y + bb.height).toBe(14 + 62);
      });
    }

    test(`WEB_3b_e2e_${name}_the_amber_unread_dot_is_9px_at_top_8_right_9_of_the_bell_until_it_is_opened`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      const dot = bell(page).locator(":scope > :not(svg)");
      await expect(dot).toHaveCount(1);
      const d = await box(dot);
      const b = await box(bell(page));
      expect([d.width, d.height]).toEqual([9, 9]);
      expect([d.y - b.y, b.x + b.width - (d.x + d.width)]).toEqual([8, 9]);
      expect((await style(dot, "background-color"))["background-color"]).toBe("rgb(240, 165, 0)");
      await bell(page).click();
      await expect(dot).toHaveCount(0);
    });

    test(`WEB_3b_e2e_${name}_the_bell_opens_the_notifications_popover_at_top_86_and_Escape_closes_it`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      await bell(page).focus();
      await bell(page).click();
      const pop = page.getByRole("dialog", { name: "Notifications" });
      await expect(pop).toBeVisible();
      const b = await box(pop);
      expect(b.y).toBe(86);
      if (wide) {
        expect(b.width).toBe(392);
        expect(b.x + b.width).toBe(viewport.width - 60); // the reference's right: 60px
      } else {
        expect(b.width).toBeLessThanOrEqual(viewport.width - 32);
      }
      expect(
        await style(pop, "position", "z-index", "border-top-left-radius", "background-color"),
      ).toEqual({
        position: "fixed",
        "z-index": "31",
        "border-top-left-radius": "20px",
        "background-color": "rgb(255, 255, 255)",
      });
      await expect(pop).toContainText("Notifications");
      await expect(pop.getByRole("button", { name: "Settings" })).toBeVisible();
      for (const t of [
        "Laptop Depot needs budget sign-off",
        "Supplier brief is waiting at the gate",
        "Competitor pricing is ready",
        "Draft reply to Northline is ready",
        "HubSpot sign-in expires in 3 days",
      ]) {
        await expect(pop.getByText(t)).toBeVisible();
      }
      await page.keyboard.press("Escape");
      await expect(pop).toHaveCount(0);
      await expect(bell(page)).toBeFocused();
    });

    test(`WEB_3b_e2e_${name}_notification_tiles_are_36_r11_amber_for_needs_green_for_done_red_for_warn`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      await bell(page).click();
      const pop = page.getByRole("dialog", { name: "Notifications" });
      const want = [
        ["Laptop Depot needs budget sign-off", "rgb(255, 231, 176)", "rgb(122, 80, 0)"],
        ["Supplier brief is waiting at the gate", "rgb(255, 231, 176)", "rgb(122, 80, 0)"],
        ["Competitor pricing is ready", "rgba(31, 127, 68, 0.12)", "rgb(30, 138, 76)"],
        ["Draft reply to Northline is ready", "rgba(31, 127, 68, 0.12)", "rgb(30, 138, 76)"],
        ["HubSpot sign-in expires in 3 days", "rgba(200, 55, 45, 0.1)", "rgb(200, 55, 45)"],
      ] as const;
      for (const [title, bg, fg] of want) {
        const row = pop.getByRole("button").filter({ hasText: title });
        const tile = row.locator(":scope > :first-child");
        const t = await box(tile);
        expect([t.width, t.height], title).toEqual([36, 36]);
        expect(
          await style(tile, "border-top-left-radius", "background-color", "color"),
          title,
        ).toEqual({
          "border-top-left-radius": "11px",
          "background-color": bg,
          color: fg,
        });
        expect((await style(row, "border-top-left-radius"))["border-top-left-radius"]).toBe("14px");
      }
    });

    test(`WEB_3b_e2e_${name}_the_avatar_opens_the_300_menu_with_header_separator_and_42px_rows`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      await avatar(page).click();
      const menu = page.getByRole("menu", { name: "Account" });
      await expect(menu).toBeVisible();
      const b = await box(menu);
      expect([b.y, b.width, b.x + b.width]).toEqual([86, 300, viewport.width - 16]);
      expect(await style(menu, "border-top-left-radius", "position")).toEqual({
        "border-top-left-radius": "20px",
        position: "fixed",
      });
      await expect(menu).toContainText("Alex Morgan");
      await expect(menu).toContainText("alex@northwind.co");
      await expect(menu).toContainText("Northwind Ops · Team plan");
      const initials = menu.getByText("AM", { exact: true });
      const i = await box(initials);
      expect([i.width, i.height]).toEqual([44, 44]);
      expect((await style(initials, "background-color"))["background-color"]).toBe(
        "rgb(230, 225, 248)",
      );
      const rule = menu.locator("div").filter({ hasNotText: /./ }).first();
      expect((await box(rule)).height).toBe(1);
      expect(
        await style(rule, "background-color", "margin-left", "margin-right", "margin-bottom"),
      ).toEqual({
        "background-color": "rgba(31, 29, 43, 0.07)",
        "margin-left": "6px",
        "margin-right": "6px",
        "margin-bottom": "4px",
      });
      const rows = menu.getByRole("menuitem");
      await expect(rows).toHaveText([
        "Profile and settings",
        "Connectors6 on",
        "Team and roles",
        "Mobile appConcept",
        "Sign out",
      ]);
      for (let k = 0; k < 5; k++) expect((await box(rows.nth(k))).height).toBe(42);
    });

    test(`WEB_3b_e2e_${name}_Sign_out_shows_the_prototype_toast_at_top_92`, async ({ page }) => {
      await open(page, "/park/home");
      await avatar(page).click();
      await page.getByRole("menuitem", { name: "Sign out" }).click();
      const toast = page.getByRole("status").filter({ hasText: "This is a prototype" });
      await expect(toast).toHaveText(/This is a prototype, so you stay signed in/);
      const t = await box(toast);
      expect(t.y).toBe(92);
      expect(Math.round(t.x + t.width / 2)).toBe(viewport.width / 2);
      expect(
        await style(
          toast,
          "border-top-left-radius",
          "background-color",
          "font-size",
          "font-weight",
        ),
      ).toEqual({
        "border-top-left-radius": "16px",
        "background-color": "rgb(31, 29, 43)",
        "font-size": "14.5px",
        "font-weight": "700",
      });
      await expect(page.getByRole("menu", { name: "Account" })).toHaveCount(0);
      expect(page.url()).toMatch(/\/park\/home$/);
    });

    test(`WEB_3b_e2e_${name}_account_links_navigate_and_the_hero_ring_shows_on_connectors`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      await avatar(page).click();
      await page.getByRole("menuitem", { name: /^Connectors/ }).click();
      await expect(page.getByTestId("park-page-connectors")).toBeVisible();
      expect(page.url()).toMatch(/\/park\/connectors$/);
      expect((await style(avatar(page), "box-shadow"))["box-shadow"]).toContain("rgb(90, 63, 224)");
      await expect(nav(page).locator('nav a[aria-current="page"]')).toHaveCount(0);
    });

    test(`WEB_3b_e2e_${name}_tabs_navigate_without_a_reload_and_the_keyboard_works`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      await page.evaluate(() => {
        Reflect.set(window, "__marker", "same document");
      });
      await tab(page, "Skills").click();
      await expect(page.getByTestId("park-page-skills")).toBeVisible();
      await expect(tab(page, "Skills")).toHaveAttribute("aria-current", "page");
      await expect(tab(page, "Home")).not.toHaveAttribute("aria-current", /.*/);
      await tab(page, "Ledger").focus();
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("park-page-ledger")).toBeVisible();
      expect(await page.evaluate(() => Reflect.get(window, "__marker"))).toBe("same document");
      await page.goBack();
      await expect(page.getByTestId("park-page-skills")).toBeVisible();
    });

    test(`WEB_3b_e2e_${name}_the_toggle_flips_data_time_draws_another_city_and_day_comes_back_the_same`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      const html = () => backdrop(page).evaluate((el) => el.innerHTML);
      const day = await html();
      await page.getByRole("button", { name: "Switch to night" }).click();
      await expect(root(page)).toHaveAttribute("data-time", "night");
      await expect(page.getByRole("button", { name: "Switch to day" })).toBeVisible();
      expect(await html()).not.toBe(day);
      await page.getByRole("button", { name: "Switch to day" }).click();
      await expect(root(page)).toHaveAttribute("data-time", "day");
      expect(await html()).toBe(day); // cached: the very same scene
    });

    test(`WEB_3b_e2e_${name}_the_backdrop_is_full_bleed_behind_everything_hidden_and_never_clickable`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      await expect(backdrop(page)).toHaveAttribute("aria-hidden", "true");
      const b = await box(backdrop(page));
      expect([b.x, b.y, b.width, b.height]).toEqual([0, 0, viewport.width, viewport.height]);
      expect(await style(backdrop(page), "position", "pointer-events", "z-index")).toEqual({
        position: "fixed",
        "pointer-events": "none",
        "z-index": "0",
      });
      const hit = await page.evaluate(
        ([x, y]) => {
          const el = document.elementFromPoint(x ?? 0, y ?? 0);
          return !!el?.closest('[aria-hidden="true"]')?.querySelector("img, svg");
        },
        [viewport.width / 2, viewport.height / 2],
      );
      expect(hit, "a click at the centre must not land on the backdrop").toBe(false);
    });

    test(`WEB_3b_e2e_${name}_the_scene_is_scaled_by_the_larger_ratio_and_centred`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      const boxes = await backdrop(page).evaluate((el) =>
        [...el.querySelectorAll("*")]
          .map((e) => e.getBoundingClientRect())
          .map((r) => [r.x, r.y, r.width, r.height]),
      );
      const s = Math.max(viewport.width / 1600, viewport.height / 1000);
      // some element is the 1600x1000 scene scaled by s and centred in the window
      const hit = boxes.find(
        ([x, y, w, h]) =>
          Math.abs((w ?? 0) - 1600 * s) < 1 &&
          Math.abs((h ?? 0) - 1000 * s) < 1 &&
          Math.abs((x ?? 0) + (w ?? 0) / 2 - viewport.width / 2) < 1 &&
          Math.abs((y ?? 0) + (h ?? 0) / 2 - viewport.height / 2) < 1,
      );
      expect(hit, JSON.stringify(boxes.slice(0, 6))).toBeDefined();
    });

    test(`WEB_3b_e2e_${name}_the_veil_dims_the_city_on_inner_pages_but_not_on_home`, async ({
      page,
    }) => {
      const PAPER = [241, 239, 233];
      const read = async (path: string) => {
        await open(page, path);
        await page.addStyleTag({ content: "main, header{display:none!important}" });
        return pixelAt(page, 10, 300);
      };
      const home = await read("/park/home");
      const inner = await read("/park/ledger");
      // --veil is rgba(241,239,233,.42) over the city: each channel is the city's own, pulled 42% to the paper
      for (let c = 0; c < 3; c++) {
        const want = (home[c] ?? 0) * 0.58 + (PAPER[c] ?? 0) * 0.42;
        expect(
          Math.abs((inner[c] ?? 0) - want),
          `channel ${c}: home ${home} inner ${inner}`,
        ).toBeLessThanOrEqual(4);
      }
    });

    test(`WEB_3b_e2e_${name}_inner_pages_sit_in_the_1320_column_with_100_24_56_padding`, async ({
      page,
    }) => {
      await open(page, "/park/ledger");
      const col = await page.getByRole("heading", { level: 1 }).evaluate((h) => {
        const out: { max: string; x: number; w: number; pad: string[] }[] = [];
        for (let e = h.parentElement; e && e.tagName !== "BODY"; e = e.parentElement) {
          const s = getComputedStyle(e);
          const r = e.getBoundingClientRect();
          out.push({
            max: s.maxWidth,
            x: r.x,
            w: r.width,
            pad: [s.paddingTop, s.paddingRight, s.paddingBottom, s.paddingLeft],
          });
        }
        return out;
      });
      const at = col.findIndex((c) => c.max === "1320px");
      expect(at, JSON.stringify(col)).toBeGreaterThanOrEqual(0);
      const c = col[at] as (typeof col)[number];
      expect(Math.round(c.x + c.w / 2)).toBe(viewport.width / 2); // centred
      expect(c.w).toBeLessThanOrEqual(1320);
      // padding 100px 24px 56px sits on the column or on the box around it
      const padded = col.slice(at).find((p) => p.pad[0] === "100px");
      expect(padded?.pad, JSON.stringify(col)).toEqual(["100px", "24px", "56px", "24px"]);
    });

    test(`WEB_3b_e2e_${name}_a_village_opens_through_the_loader_then_the_page`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      await bell(page).click();
      await page.getByRole("button", { name: /Competitor pricing is ready/ }).click();
      await expect(loader(page)).toBeVisible();
      await expect(loader(page)).toContainText("OPENING VILLAGE");
      await expect(loader(page)).toContainText("Competitor pricing");
      await expect(loader(page)).toContainText("Quick task · 1 agent");
      await expect(loader(page)).toContainText("Loading the task");
      expect(await style(loader(page), "position", "z-index", "background-color")).toEqual({
        position: "fixed",
        "z-index": "40",
        "background-color": "rgba(241, 239, 233, 0.55)",
      });
      const card = loader(page).locator(":scope > *").first();
      expect((await box(card)).width).toBe(Math.min(400, viewport.width - 48));
      expect(await style(card, "border-top-left-radius", "padding", "row-gap")).toEqual({
        "border-top-left-radius": "24px",
        padding: "22px 24px 24px",
        "row-gap": "18px",
      });
      await expect(page.getByRole("dialog", { name: "Notifications" })).toHaveCount(0);
      expect(page.url()).toMatch(/\/park\/home$/); // the old page stays until step 3
      await expect(page).toHaveURL(/\/park\/world\/comp$/, { timeout: 3000 });
      await expect(page.getByTestId("park-page-world")).toBeVisible({ timeout: 3000 });
      await expect(loader(page)).toHaveCount(0, { timeout: 3000 });
    });

    test(`WEB_3b_e2e_${name}_a_city_loader_says_OPENING_CITY_shows_a_16px_ring_and_waits_for_step_3`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      await bell(page).click();
      await page.getByRole("button", { name: /Laptop Depot needs budget sign-off/ }).click();
      await expect(loader(page)).toContainText("OPENING CITY");
      await expect(loader(page)).toContainText("K1 electric scooter");
      await expect(loader(page)).toContainText("Workspace · 38 agents");
      await expect(loader(page)).toContainText("Waking 38 agents");
      const rings = await loader(page).evaluate(
        (l) =>
          [...l.querySelectorAll("*")].filter((e) => {
            const s = getComputedStyle(e);
            const r = e.getBoundingClientRect();
            return (
              Math.round(r.width) === 16 &&
              Math.round(r.height) === 16 &&
              s.borderTopColor === "rgb(90, 63, 224)"
            );
          }).length,
      );
      expect(rings, "the active step shows a 16px ring").toBe(1);
      expect(page.url()).toMatch(/\/park\/home$/); // the swap is at the third 340 ms tick, about 1 s
      await expect(page).toHaveURL(/\/park\/world\/k1$/, { timeout: 3000 });
      await expect(loader(page)).toHaveCount(0, { timeout: 3000 });
    });

    test(`WEB_3b_e2e_${name}_the_sample_data_chip_is_visible_and_explains_itself`, async ({
      page,
    }) => {
      await open(page, "/park/home");
      const chip = nav(page).getByRole("button", { name: "Sample data" });
      await expect(chip).toBeVisible();
      const b = await box(chip);
      expect(b.x).toBeGreaterThanOrEqual(0);
      expect(b.x + b.width).toBeLessThanOrEqual(viewport.width);
      await chip.click();
      await expect(
        page.getByText(
          "Northwind Ops is a fictional team. Amounts are examples (£), dates are September 2026.",
        ),
      ).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog", { name: "Sample data" })).toHaveCount(0);
    });

    test(`WEB_3b_e2e_${name}_the_shell_logs_no_console_error_through_a_tour`, async ({ page }) => {
      const problems = collectConsoleProblems(page);
      await open(page, "/park/home");
      await bell(page).click();
      await page.keyboard.press("Escape");
      await avatar(page).click();
      await page.getByRole("menuitem", { name: "Team and roles" }).click();
      await expect(page.getByTestId("park-page-team")).toBeVisible();
      await page.getByRole("button", { name: "Switch to night" }).click();
      await tab(page, "Worlds").click();
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
        const bad = results.violations.filter(
          (v) => v.impact === "serious" || v.impact === "critical",
        );
        expect(bad, `${path}: ${JSON.stringify(bad, null, 2)}`).toEqual([]);
      }
    });

    test(`WEB_3b_e2e_${name}_the_page_does_not_scroll_sideways_with_a_popover_open`, async ({
      page,
    }) => {
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
    const css = await nav(page)
      .locator("nav")
      .evaluate((el) => ({
        overflowX: getComputedStyle(el).overflowX,
        scroll: el.scrollWidth,
        client: el.clientWidth,
      }));
    expect(css.overflowX).toBe("auto");
    expect(css.scroll).toBeGreaterThan(css.client); // six tabs do not fit the strip at 390
    const bar = await box(nav(page));
    expect(bar.x + bar.width).toBe(MOBILE.width - 16);
  });
});
