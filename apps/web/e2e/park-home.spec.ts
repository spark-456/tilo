// WEB-4 acceptance (plan sections 8a and 10; README "Home"): / (home) in a real browser at 1440x900 and
// 390x844, day and night. Home runs alone inside ParkApp here (the shell, WEB-3b, adds the nav and the city).
// Every expected number was measured as a computed value on the reference page, served from
// design_handoff_tilo_web_app/design (`python -m http.server <port>`, open `Tilo App.dc.html#home`) at the
// same viewports; the ones that are `calc()` values of the container are checked against the container
// (the Home root: position relative, height 100vh), so they hold with or without the shell.
//   - panels: hero 500 wide (max 100% - 48), Today panel 352 wide, composer column 1040 wide, glass fill,
//     border, blur, radius 28 / 26 / 28, paddings 24 26 22 / 8 / 10, gaps 12 / 6 / 8;
//   - type: h1 Nunito 900 50 / -1.4 / 50, summary 17/600, rows 14/800 and 12.5/700, composer 20/700;
//   - copy and the flow: composer idle -> drafting -> plan -> Change brief -> start -> toast Open, in real time;
//   - Review opens /world/k1; no console error, no sideways scroll at 390, axe finds nothing serious.
// Night: the shell flips `data-time` on the data-park root; here the attribute is set on the page, which is
// all the CSS reads (colours are tokens), so this checks the night tokens reach every part of Home.
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-home.spec.ts --project=chromium --no-deps --workers=1
import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";
import { DESKTOP, MOBILE } from "./support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;
type Theme = "day" | "night";

// P0-08b W4: DEMO-TIME-1 follows the browser's calendar. Fix Date while leaving
// real timers running for drafting, transitions and the toast flow.
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date(2026, 8, 24, 12));
});

// ---- reference values (computed, 1440x900 and 390x844) -----------------------------------------------
const TOKENS = {
  day: {
    gBg: "rgba(255, 255, 255, 0.72)",
    gBd: "rgba(255, 255, 255, 0.85)",
    fx: "blur(20px) saturate(1.5)",
    sh: "rgba(31, 29, 43, 0.06) 0px 1px 2px 0px, rgba(31, 29, 43, 0.45) 0px 18px 40px -24px",
    ink: "rgb(31, 29, 43)",
    ink2: "rgb(74, 70, 85)",
    ink3: "rgb(107, 103, 121)",
    hero: "rgb(90, 63, 224)",
    heroInk: "rgb(74, 49, 204)",
    seg: "rgba(31, 29, 43, 0.06)",
    tabOn: "rgb(255, 255, 255)",
    amberSoft: "rgb(255, 244, 218)",
    amberLine: "rgb(241, 212, 140)",
    amberTile: "rgb(255, 231, 176)",
    amberInk: "rgb(122, 80, 0)",
    track: "rgba(31, 29, 43, 0.1)",
    sunk: "rgba(31, 29, 43, 0.043)",
    run: "rgb(90, 63, 224)",
    line2: "rgba(31, 29, 43, 0.07)",
    pop: "rgb(255, 255, 255)",
  },
  night: {
    gBg: "rgba(20, 22, 52, 0.66)",
    gBd: "rgba(255, 255, 255, 0.14)",
    fx: "blur(20px) saturate(1.4)",
    sh: "rgba(0, 0, 0, 0.3) 0px 1px 2px 0px, rgba(0, 0, 0, 0.75) 0px 18px 40px -24px",
    ink: "rgb(244, 242, 250)",
    ink2: "rgb(210, 206, 227)",
    ink3: "rgb(210, 206, 227)", // not measured at night: unused by the checks below
    // W4 supervisor ruling: BQ-DS-A11Y-1 gives WCAG AA precedence over the export.
    hero: "rgb(108, 82, 235)",
    heroInk: "rgb(188, 175, 255)",
    seg: "rgba(255, 255, 255, 0.08)",
    tabOn: "rgba(255, 255, 255, 0.16)",
    amberSoft: "rgba(58, 42, 16, 0.85)",
    amberLine: "rgba(247, 200, 92, 0.45)",
    amberTile: "rgb(74, 56, 16)",
    amberInk: "rgb(247, 200, 92)",
    track: "rgba(255, 255, 255, 0.14)",
    sunk: "rgba(255, 255, 255, 0.05)",
    run: "rgb(164, 147, 255)",
    line2: "rgba(255, 255, 255, 0.07)",
    pop: "rgb(35, 38, 79)",
  },
} as const;

const RING = {
  outlineStyle: "solid",
  outlineWidth: "3px",
  outlineColor: "rgb(90, 63, 224)",
  outlineOffset: "2px",
};

// Design-owned contrast exceptions (plan 8c: the design's own values win and the PR lists them): at night
// white on the hero button fill #7A62F5 is 4.29:1 (the Start task and Start now buttons), and the selected
// "Size of job" label #BCAFFF on the thumb over the night glass is 4.33:1. Matched by colour pair, never
// by selector, so a different element with the same failure is still reported.
const DESIGN_OWNED_CONTRAST = [
  ["#ffffff", "#7a62f5"],
  ["#bcafff", "#494b64"],
] as const;
function isDesignOwnedContrast(node: { any: { data?: unknown }[] }): boolean {
  return node.any.some((check) => {
    const d = check.data as { fgColor?: string; bgColor?: string } | undefined;
    return DESIGN_OWNED_CONTRAST.some(([fg, bg]) => d?.fgColor === fg && d?.bgColor === bg);
  });
}

// ---- helpers -----------------------------------------------------------------------------------------
type Facts = Record<string, string | number>;

/** Computed values of an element (or, with `glass`, of its nearest ancestor that has a backdrop blur),
 * its box, and the box of its containing block (the Home root for an absolutely placed panel). */
async function facts(loc: Locator, props: readonly string[], glass = false): Promise<Facts> {
  return loc.evaluate(
    (el, arg) => {
      let n: Element = el;
      if (arg.glass) {
        while (n.parentElement && getComputedStyle(n).backdropFilter === "none")
          n = n.parentElement;
      }
      const s = getComputedStyle(n);
      const r = n.getBoundingClientRect();
      const out: Record<string, string | number> = { x: r.x, y: r.y, w: r.width, h: r.height };
      for (const p of arg.props) out[p] = s.getPropertyValue(p);
      const cb = (n as HTMLElement).offsetParent;
      if (cb) {
        const c = cb.getBoundingClientRect();
        out.cbW = c.width;
        out.cbH = c.height;
      }
      return out;
    },
    { props, glass },
  );
}

/** Every wanted computed value is equal to what the page resolves (colours and lengths as the browser prints them). */
function expectFacts(label: string, got: Facts, want: Record<string, string>) {
  for (const [k, v] of Object.entries(want)) expect(got[k], `${label} ${k}`).toBe(v);
}

const near = (label: string, got: number, want: number, tol = 1.5) =>
  expect(Math.abs(got - want), `${label}: ${got} vs ${want}`).toBeLessThanOrEqual(tol);

async function openHome(page: Page, theme: Theme): Promise<string[]> {
  const problems = collectConsoleProblems(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    /^Good (morning|evening), Alex\.$/,
  );
  await expect(page.getByRole("button", { name: "Start task", exact: true })).toBeVisible();
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  if (theme === "night") {
    await page.locator("[data-park]").evaluate((el) => el.setAttribute("data-time", "night"));
  }
  return problems;
}

const hero = (page: Page) => page.getByRole("heading", { level: 1 });

test("P0_08b_W4_sample_calendar_matches_the_reference_day", async ({ page }) => {
  await openHome(page, "day");
  await expect(page.getByText("THURSDAY 24 SEPTEMBER", { exact: true })).toBeVisible({
    timeout: 5000,
  });
});
const today = (page: Page) => page.locator('aside[aria-label="Today"]');
const input = (page: Page) => page.getByRole("textbox", { name: "Describe your task" });
const start = (page: Page) => page.getByRole("button", { name: "Start task", exact: true });
const size = (page: Page) => page.locator('[aria-label="Size of job"]');
const row = (page: Page, name: string) =>
  today(page).getByRole("button", { name: new RegExp(name) });
const pill = (page: Page) =>
  page.getByRole("button", { name: /\d decisions? waiting in K1 electric scooter/ });
const caught = (page: Page) => page.getByText("You’re all caught up");

// A cold Vite dev server optimises its dependencies on the first request and reloads the page; warm it
// once per worker so no test pays for it.
test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(150_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/", { timeout: 120_000 });
  await page
    .getByRole("heading", { level: 1 })
    .waitFor({ timeout: 120_000 })
    .catch(() => undefined);
  await page.close();
});

for (const [sizeName, viewport] of Object.entries(SIZES)) {
  const wide = viewport.width >= 1180;
  for (const theme of ["day", "night"] as const) {
    const T = TOKENS[theme];
    test.describe(`park home at ${sizeName}, ${theme}`, () => {
      test.use({ viewport });

      test(`WEB_4_e2e_${sizeName}_${theme}_the_panels_and_their_boxes_match_the_reference`, async ({
        page,
      }) => {
        const problems = await openHome(page, theme);
        const vh = viewport.height;

        // The Home root: the containing block of the three panels, a full-height positioned box.
        const root = await page.getByTestId("park-page-home").evaluate((el) => {
          const s = getComputedStyle(el);
          return {
            position: s.position,
            height: el.getBoundingClientRect().height,
            width: el.getBoundingClientRect().width,
            overflow: s.overflow,
          };
        });
        expect(root.position).toBe("relative");
        near("root height is 100vh (min 720)", root.height, Math.max(vh, 720));
        // A phone's root scrolls (x hidden, y auto) so the greeting and composer stack without overlap (13 Oct QA).
        expect(root.overflow).toBe(sizeName === "mobile" ? "hidden auto" : "hidden");

        // Hero panel: left 24, top 96, 500 wide (at most the root less 48), glass, r28, p 24 26 22, gap 12.
        const heroP = await facts(
          hero(page),
          [
            "position",
            "left",
            "top",
            "padding",
            "border-top-left-radius",
            "border-top-width",
            "border-top-color",
            "background-color",
            "backdrop-filter",
            "box-shadow",
            "gap",
            "z-index",
            "display",
            "flex-direction",
          ],
          true,
        );
        expectFacts("hero", heroP, {
          // W4: #995 / f60aa4eb and the 13 Oct QA layout place the hero in a column.
          position: "static",
          left: "auto",
          top: "auto",
          padding: sizeName === "mobile" ? "20px 22px 18px" : "24px 26px 22px",
          "border-top-left-radius": "28px",
          "border-top-width": "1px",
          "border-top-color": T.gBd,
          "background-color": T.gBg,
          "backdrop-filter": T.fx,
          "box-shadow": T.sh,
          gap: sizeName === "mobile" ? "10px" : "12px",
          "z-index": "3",
          display: "flex",
          "flex-direction": "column",
        });
        const leftColumn = await facts(page.locator(".park-home-leftcol"), [
          "position",
          "left",
          "top",
        ]);
        expectFacts("hero column (#995)", leftColumn, {
          position: sizeName === "mobile" ? "static" : "absolute",
          left: "24px",
          top: "96px",
        });
        near("hero width", Number(heroP.w), Math.min(500, root.width - 48));
        if (wide) near("hero height (reference: 292.8 at 500 wide)", Number(heroP.h), 292.8, 3);

        // Today panel (only from 1180): right 24, top 96, 352 wide, p 8, r26, gap 6, scrolls, max height root - 330.
        if (wide) {
          const aside = await facts(today(page), [
            "position",
            "right",
            "top",
            "padding",
            "border-top-left-radius",
            "background-color",
            "backdrop-filter",
            "box-shadow",
            "gap",
            "overflow-y",
            "z-index",
          ]);
          expectFacts("today", aside, {
            position: "absolute",
            right: "24px",
            top: "96px",
            padding: "8px",
            "border-top-left-radius": "26px",
            "background-color": T.gBg,
            "backdrop-filter": T.fx,
            "box-shadow": T.sh,
            gap: "6px",
            "overflow-y": "auto",
            "z-index": "3",
          });
          near("today width", Number(aside.w), 352);
          near(
            "today max height = root - 330 (content is taller)",
            Number(aside.h),
            Number(aside.cbH) - 330,
            1,
          );
        } else {
          await expect(today(page)).toHaveCount(0);
        }

        // Composer column: bottom 24, 1040 wide (at most the root less 48), the glass panel r28 p10 gap 8.
        const panel = await facts(
          input(page),
          [
            "position",
            "padding",
            "border-top-left-radius",
            "border-top-width",
            "border-top-color",
            "background-color",
            "backdrop-filter",
            "box-shadow",
            "gap",
          ],
          true,
        );
        expectFacts("composer panel", panel, {
          padding: "10px",
          "border-top-left-radius": "28px",
          "border-top-width": "1px",
          "border-top-color": T.gBd,
          "background-color": T.gBg,
          "backdrop-filter": T.fx,
          "box-shadow": T.sh,
          gap: "8px",
        });
        // The column is the composer's own box; the Home root is its containing block.
        const column = await input(page).evaluate((el) => {
          const col = el.closest<HTMLElement>(".park-home-composer");
          if (!col) throw new Error("no composer column above the input");
          const s = getComputedStyle(col);
          return {
            position: s.position,
            bottom: s.bottom,
            zIndex: s.zIndex,
            gap: s.gap,
            width: col.getBoundingClientRect().width,
            rootWidth: (col.offsetParent as HTMLElement).getBoundingClientRect().width,
          };
        });
        // On a phone (13 Oct QA) the column sits in the page's scrolling flow, not pinned 24px from the bottom.
        expect(column).toMatchObject(
          sizeName === "mobile"
            ? { position: "static", gap: "12px" }
            : { position: "absolute", bottom: "24px", zIndex: "4", gap: "12px" },
        );
        const columnWidth = Math.min(1040, column.rootWidth - 48);
        near("composer column width", column.width, columnWidth);
        near("composer panel fills the column", Number(panel.w), columnWidth);
        expect(problems).toEqual([]);
      });

      test(`WEB_4_e2e_${sizeName}_${theme}_greeting_type_and_copy_match_the_reference`, async ({
        page,
      }) => {
        const problems = await openHome(page, theme);
        const h1 = await facts(hero(page), [
          "font-family",
          "font-size",
          "font-weight",
          "letter-spacing",
          "line-height",
          "color",
          "margin-top",
        ]);
        expect(String(h1["font-family"])).toMatch(/^"?Nunito"?,/);
        expectFacts("h1", h1, {
          // W4: phone typography follows the 13 Oct responsive rules (#995).
          "font-size": sizeName === "mobile" ? "40px" : "50px",
          "font-weight": "900",
          "letter-spacing": sizeName === "mobile" ? "-1.1px" : "-1.4px",
          "line-height": sizeName === "mobile" ? "40px" : "50px",
          color: T.ink,
          "margin-top": "0px",
        });
        // The date line: 13/800, +0.7px, ink2, in capitals as seen.
        const date = page.getByText(/^thursday 24 september( · 21:10)?$/i);
        expect(await date.innerText()).toBe("THURSDAY 24 SEPTEMBER");
        expectFacts(
          "date",
          await facts(date, ["font-size", "font-weight", "letter-spacing", "color"]),
          {
            "font-size": "13px",
            "font-weight": "800",
            "letter-spacing": "0.7px",
            color: T.ink2,
          },
        );
        // Summary: 17/600, lh 1.45, ink2 (copy of the day state; the night line is checked in the unit tests).
        const summary = page.getByText(
          "38 agents are at work across 4 worlds. Two things need you.",
        );
        expectFacts(
          "summary",
          await facts(summary, ["font-size", "font-weight", "line-height", "color"]),
          {
            "font-size": "17px",
            "font-weight": "600",
            "line-height": "24.65px",
            color: T.ink2,
          },
        );
        // Needs pill: amber soft, 1px amber line, r999, p 4 5 4 4, 14.5/600, gap 10; Review chip h30 amber.
        const p = await facts(pill(page), [
          "padding",
          "border-top-left-radius",
          "background-color",
          "border-top-width",
          "border-top-color",
          "font-size",
          "gap",
          "color",
        ]);
        expectFacts("needs pill", p, {
          padding: "4px 5px 4px 4px",
          "border-top-left-radius": "999px",
          "background-color": T.amberSoft,
          "border-top-width": "1px",
          "border-top-color": T.amberLine,
          "font-size": "14.5px",
          gap: "10px",
          color: T.ink,
        });
        if (wide) near("pill height", Number(p.h), 42); // narrow: the line wraps, so no fixed height
        const review = pill(page).getByText("Review", { exact: true });
        const chip = await facts(review, [
          "background-color",
          "color",
          "padding",
          "font-size",
          "font-weight",
          "border-top-left-radius",
        ]);
        expectFacts("review chip", chip, {
          "background-color": "rgb(240, 165, 0)",
          color: "rgb(31, 29, 43)",
          padding: "0px 14px",
          "font-size": "13.5px",
          "font-weight": "800",
          "border-top-left-radius": "999px",
        });
        near("review chip height", Number(chip.h), 30);
        expect(await pill(page).innerText()).toMatch(
          /^2 decisions waiting in K1 electric scooter\s+Review$/,
        );
        expect(problems).toEqual([]);
      });

      if (wide) {
        test(`WEB_4_e2e_${sizeName}_${theme}_the_Today_panel_rows_match_the_reference`, async ({
          page,
        }) => {
          const problems = await openHome(page, theme);
          // Copy of the three sections and their links.
          // the fixture rows are sample data, so the section is not titled "Live now" (HR-1)
          for (const t of [
            "Sample worlds",
            "All worlds",
            "Up next today",
            "Agenda",
            "September spend",
            "Ledger",
          ]) {
            await expect(today(page).getByText(t, { exact: true })).toBeVisible();
          }
          const title = await facts(today(page).getByText("Sample worlds", { exact: true }), [
            "font-size",
            "font-weight",
            "color",
          ]);
          expectFacts("Sample worlds", title, {
            "font-size": "15px",
            "font-weight": "800",
            color: T.ink,
          });
          const link = await facts(today(page).getByText("All worlds", { exact: true }), [
            "font-size",
            "font-weight",
            "color",
          ]);
          expectFacts("All worlds", link, {
            "font-size": "13.5px",
            "font-weight": "800",
            color: T.heroInk,
          });

          // K1 row (needs): grid 40 / 1fr / auto, gap 12, p 7 10 7 7, r16, amber tile, amber-ink sub, amber bar at 46%.
          const k1 = await facts(row(page, "K1 electric scooter"), [
            "display",
            "grid-template-columns",
            "gap",
            "padding",
            "border-top-left-radius",
          ]);
          expectFacts("K1 row", k1, {
            display: "grid",
            gap: "12px",
            padding: "7px 10px 7px 7px",
            "border-top-left-radius": "16px",
          });
          near("row height", Number(k1.h), 54);
          // 334 inside the panel, 319 where the panel's scrollbar takes 15px (as in the reference's browser).
          expect(
            [319, 334].some((w) => Math.abs(Number(k1.w) - w) < 1),
            `row width ${k1.w}`,
          ).toBe(true);
          // Columns: 40px tile, the rest, 44px track (the middle is what is left after padding and 2 gaps).
          const cols = /^40px ([\d.]+)px 44px$/.exec(String(k1["grid-template-columns"]));
          expect(cols, `columns ${k1["grid-template-columns"]}`).not.toBeNull();
          near("middle column", Number(cols?.[1]), Number(k1.w) - 17 - 40 - 44 - 24, 1);
          const parts = await row(page, "K1 electric scooter").evaluate((el) => {
            const kids = [...el.children] as HTMLElement[];
            const [tile, text, track] = kids;
            const cs = (e: Element | undefined, p: string) =>
              e ? getComputedStyle(e).getPropertyValue(p) : "";
            const [name, sub] = [...(text?.children ?? [])];
            const bar = track?.firstElementChild;
            return {
              tileBg: cs(tile, "background-color"),
              tileSize: tile?.getBoundingClientRect().width,
              tileRadius: cs(tile, "border-top-left-radius"),
              name: [cs(name, "font-size"), cs(name, "font-weight"), name?.textContent],
              sub: [
                cs(sub, "font-size"),
                cs(sub, "font-weight"),
                cs(sub, "color"),
                sub?.textContent,
              ],
              trackBg: cs(track, "background-color"),
              trackW: track?.getBoundingClientRect().width,
              trackH: track?.getBoundingClientRect().height,
              barBg: cs(bar ?? undefined, "background-color"),
              barW: bar?.getBoundingClientRect().width,
            };
          });
          expect(parts.tileBg).toBe(T.amberTile);
          expect(parts.tileSize).toBeCloseTo(40, 0);
          expect(parts.tileRadius).toBe("12px");
          expect(parts.name).toEqual(["14px", "800", "K1 electric scooter"]);
          expect(parts.sub).toEqual(["12.5px", "700", T.amberInk, "2 decisions waiting"]);
          expect(parts.trackBg).toBe(T.track);
          near("track width", Number(parts.trackW), 44);
          near("track height", Number(parts.trackH), 5);
          expect(parts.barBg).toBe("rgb(240, 165, 0)");
          near("K1 bar fills 46%", Number(parts.barW) / Number(parts.trackW), 0.46, 0.01);
          // A running row: sunk tile, ink2 sub, run-coloured bar at 58%.
          const hires = await row(page, "Onboard 12 new hires").evaluate((el) => {
            const [tile, text, track] = [...el.children] as HTMLElement[];
            const cs = (e: Element | undefined, p: string) =>
              e ? getComputedStyle(e).getPropertyValue(p) : "";
            return {
              tileBg: cs(tile, "background-color"),
              subColor: cs(text?.children[1], "color"),
              barBg: cs(track?.firstElementChild ?? undefined, "background-color"),
              ratio:
                (track?.firstElementChild?.getBoundingClientRect().width ?? 0) /
                (track?.getBoundingClientRect().width ?? 1),
            };
          });
          expect(hires.tileBg).toBe(T.sunk);
          expect(hires.subColor).toBe(T.ink2);
          expect(hires.barBg).toBe(T.run);
          near("hires bar fills 58%", hires.ratio, 0.58, 0.01);

          // Up next: two events, grid 52 / 1fr, p 8 10, r14, a 3px work-blue bar, 14/800 title, 12.5/700 sub.
          const ev = today(page).getByRole("button", { name: /Focus · Q4 plan/ });
          expect(await ev.innerText()).toMatch(
            /^10:30\s+Focus · Q4 plan\s+Google Calendar · 90 min$/,
          );
          const evF = await facts(ev, [
            "display",
            "grid-template-columns",
            "padding",
            "border-top-left-radius",
            "gap",
          ]);
          expectFacts("event row", evF, {
            display: "grid",
            padding: "8px 10px",
            "border-top-left-radius": "14px",
            gap: "12px",
          });
          const evCols = /^52px ([\d.]+)px$/.exec(String(evF["grid-template-columns"]));
          expect(evCols, `columns ${evF["grid-template-columns"]}`).not.toBeNull();
          near("event body column", Number(evCols?.[1]), Number(evF.w) - 20 - 52 - 12, 1);
          near("event row height", Number(evF.h), 53.2);
          const evParts = await ev.evaluate((el) => {
            const [time, body] = [...el.children] as HTMLElement[];
            const cs = (e: Element | undefined, p: string) =>
              e ? getComputedStyle(e).getPropertyValue(p) : "";
            return {
              time: [cs(time, "font-size"), cs(time, "font-weight"), cs(time, "color")],
              border: [
                cs(body, "border-left-width"),
                cs(body, "border-left-style"),
                cs(body, "border-left-color"),
                cs(body, "padding-left"),
              ],
              title: [
                cs(body?.children[0], "font-size"),
                cs(body?.children[0], "font-weight"),
                cs(body?.children[0], "line-height"),
              ],
              sub: [
                cs(body?.children[1], "font-size"),
                cs(body?.children[1], "font-weight"),
                cs(body?.children[1], "color"),
              ],
            };
          });
          expect(evParts.time).toEqual(["14px", "800", T.ink2]);
          expect(evParts.border).toEqual(["3px", "solid", T.hero, "10px"]);
          expect(evParts.title).toEqual(["14px", "800", "18.2px"]);
          expect(evParts.sub).toEqual(["12.5px", "700", T.ink2]);
          await expect(
            today(page).getByRole("button", { name: /Supplier sync · Northline/ }),
          ).toContainText("Tilo’s brief is ready");

          // September spend: p 10 10 12, r16, gap 8; 24/800 -0.4 amount; bars 30% and 43% of a 6px track.
          const spend = today(page).getByRole("button", { name: /September spend/ });
          expectFacts(
            "spend",
            await facts(spend, [
              "display",
              "flex-direction",
              "padding",
              "border-top-left-radius",
              "gap",
            ]),
            {
              display: "flex",
              "flex-direction": "column",
              padding: "10px 10px 12px",
              "border-top-left-radius": "16px",
              gap: "8px",
            },
          );
          expectFacts(
            "spend amount",
            await facts(spend.getByText("£2,412", { exact: true }), [
              "font-size",
              "font-weight",
              "letter-spacing",
              "color",
            ]),
            {
              "font-size": "24px",
              "font-weight": "800",
              "letter-spacing": "-0.4px",
              color: T.ink,
            },
          );
          expectFacts(
            "spend of",
            await facts(spend.getByText("of £8,000", { exact: true }), [
              "font-size",
              "font-weight",
              "color",
            ]),
            {
              "font-size": "13.5px",
              "font-weight": "700",
              color: T.ink2,
            },
          );
          expectFacts(
            "spend forecast",
            await facts(
              spend.getByText("Forecast £6,300 · £3,420 waiting on you", { exact: true }),
              ["font-size", "font-weight", "color"],
            ),
            {
              "font-size": "12.5px",
              "font-weight": "700",
              color: T.ink2,
            },
          );
          const bars = await spend.evaluate((el) => {
            const sixes = [...el.querySelectorAll("*")].filter(
              (e) => Math.abs(e.getBoundingClientRect().height - 6) < 0.1,
            );
            const [track, a, b] = sixes as HTMLElement[];
            const w = track?.getBoundingClientRect().width ?? 1;
            return {
              n: sixes.length,
              a: (a?.getBoundingClientRect().width ?? 0) / w,
              b: (b?.getBoundingClientRect().width ?? 0) / w,
              aBg: a ? getComputedStyle(a).backgroundColor : "",
              bBg: b ? getComputedStyle(b).backgroundColor : "",
              bOpacity: b ? getComputedStyle(b).opacity : "",
              trackBg: track ? getComputedStyle(track).backgroundColor : "",
            };
          });
          expect(bars.n).toBe(3);
          near("spent segment 30%", bars.a, 0.3, 0.005);
          near("waiting segment 43%", bars.b, 0.43, 0.005);
          expect(bars.aBg).toBe(T.hero);
          expect(bars.bBg).toBe("rgb(240, 165, 0)");
          expect(bars.bOpacity).toBe("0.85");
          expect(bars.trackBg).toBe(T.track);
          expect(problems).toEqual([]);
        });
      }

      test(`WEB_4_e2e_${sizeName}_${theme}_the_composer_matches_the_reference`, async ({
        page,
      }) => {
        const problems = await openHome(page, theme);
        const f = await facts(input(page), ["font-size", "font-weight", "color", "font-family"]);
        // W4: #995 retains the short phone placeholder and 13 Oct's 16px input type.
        expectFacts("input", f, {
          "font-size": sizeName === "mobile" ? "16px" : "20px",
          "font-weight": "700",
          color: T.ink,
        });
        expect(String(f["font-family"])).toMatch(/Nunito Sans/);
        near("input height", Number(f.h), 60);
        // A phone's input cannot wrap its placeholder, so it shows the example in few words (13 Oct QA).
        expect(await input(page).getAttribute("placeholder")).toBe(
          sizeName === "mobile"
            ? "e.g. Summarise this week’s feedback"
            : "e.g. Summarise this week’s customer feedback",
        );
        const s = await facts(start(page), [
          "background-color",
          "color",
          "padding",
          "font-size",
          "font-weight",
          "border-top-left-radius",
          "border-top-width",
        ]);
        expectFacts("start", s, {
          "background-color": T.hero,
          color: "rgb(255, 255, 255)",
          padding: "0px 24px",
          "font-size": "16px",
          "font-weight": "800",
          "border-top-left-radius": "18px",
          "border-top-width": "0px",
        });
        near("start height", Number(s.h), 54);
        near("start width", Number(s.w), 123.67, 3);
        // Size of job: a 390 track (at most its row), p4 r16, 36px items 14/800, thumb r12; one third each.
        const g = await facts(size(page), [
          "display",
          "padding",
          "border-top-left-radius",
          "background-color",
          "grid-template-columns",
        ]);
        expectFacts("size of job", g, {
          display: "grid",
          padding: "4px",
          "border-top-left-radius": "16px",
          "background-color": T.seg,
        });
        const rowW = await size(page).evaluate((el) => {
          const p = el.parentElement as HTMLElement;
          const ps = getComputedStyle(p);
          return (
            p.clientWidth - Number.parseFloat(ps.paddingLeft) - Number.parseFloat(ps.paddingRight)
          );
        });
        near("size of job width", Number(g.w), Math.min(390, rowW));
        const opts = await size(page).evaluate((el) => {
          const items = [...el.querySelectorAll<HTMLElement>('[role="radio"], [role="tab"]')];
          return items.map((e) => ({
            t: e.textContent,
            h: e.getBoundingClientRect().height,
            w: e.getBoundingClientRect().width,
            fs: getComputedStyle(e).fontSize,
            fw: getComputedStyle(e).fontWeight,
            c: getComputedStyle(e).color,
          }));
        });
        expect(opts.map((o) => o.t)).toEqual(["Quick task", "Routine", "Workspace"]);
        for (const o of opts) {
          near(`${o.t} height`, o.h, 36);
          near(`${o.t} width is a third of the inside`, o.w, (Number(g.w) - 8) / 3, 1);
          expect([o.fs, o.fw]).toEqual(["14px", "800"]);
        }
        expect(opts[0]?.c).toBe(T.heroInk); // the selected label
        expect(opts[1]?.c).toBe(T.ink2);
        const thumb = await facts(size(page).locator('[aria-hidden="true"]').first(), [
          "background-color",
          "border-top-left-radius",
          "box-shadow",
        ]);
        expectFacts("thumb", thumb, {
          "background-color": T.tabOn,
          "border-top-left-radius": "12px",
        });
        near(
          "thumb left edge sits at the track's 4px padding",
          Number(thumb.x) - Number(g.x),
          4,
          1.5,
        );
        near("thumb width is a third of the inside", Number(thumb.w), (Number(g.w) - 8) / 3, 1);
        // Hint and chips.
        const hint = await facts(
          page.getByText("You see the plan and the cost before any agent starts."),
          ["font-size", "font-weight", "color", "line-height"],
        );
        expectFacts("hint", hint, {
          "font-size": "14px",
          "font-weight": "700",
          color: T.ink2,
          "line-height": "18.9px",
        });
        for (const label of [
          "Compare three suppliers",
          "Draft a reply to Northline",
          "Summarise yesterday’s calls",
        ]) {
          const c = await facts(page.getByRole("button", { name: label, exact: true }), [
            "padding",
            "border-top-left-radius",
            "background-color",
            "border-top-color",
            "backdrop-filter",
            "font-size",
            "font-weight",
            "color",
          ]);
          expectFacts(label, c, {
            padding: "0px 16px",
            "border-top-left-radius": "999px",
            "background-color": T.gBg,
            "border-top-color": T.gBd,
            "backdrop-filter": T.fx,
            "font-size": "14px",
            "font-weight": "800",
            color: T.ink,
          });
          near(`${label} height`, Number(c.h), 38);
        }
        expect(problems).toEqual([]);
      });

      test(`WEB_4_e2e_${sizeName}_${theme}_the_page_does_not_scroll_sideways_and_axe_finds_nothing_serious`, async ({
        page,
      }) => {
        test.setTimeout(90_000);
        const problems = await openHome(page, theme);
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(overflow).toBeLessThanOrEqual(0);
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
          .analyze();
        const bad = results.violations
          .filter((v) => v.impact === "serious" || v.impact === "critical")
          .map((v) => ({
            id: v.id,
            nodes: v.nodes.filter((n) => !(v.id === "color-contrast" && isDesignOwnedContrast(n))),
          }))
          .filter((v) => v.nodes.length > 0);
        expect(
          bad,
          JSON.stringify(
            bad.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) })),
            null,
            2,
          ),
        ).toEqual([]);
        expect(problems).toEqual([]);
      });
    });
  }

  test.describe(`park home at ${sizeName}: the flow, in real time`, () => {
    test.use({ viewport });

    test(`WEB_4_e2e_${sizeName}_composer_idle_drafting_plan_change_brief_start_toast_open`, async ({
      page,
    }) => {
      test.setTimeout(60_000);
      const problems = await openHome(page, "day");
      await input(page).fill("Compare three suppliers");
      await start(page).click();
      // Drafting at once, a plan inside 3 s (the design's 900 ms).
      const drafting = page
        .getByRole("status")
        .filter({ hasText: "Tilo is drafting a village for “Compare three suppliers”" });
      await expect(drafting).toBeVisible();
      const d = await facts(drafting, [
        "height",
        "padding",
        "border-top-left-radius",
        "background-color",
        "font-size",
        "font-weight",
        "gap",
      ]);
      expectFacts("drafting line", d, {
        height: "44px",
        padding: "0px 18px 0px 14px",
        "border-top-left-radius": "999px",
        "background-color": TOKENS.day.pop,
        "font-size": "14.5px",
        "font-weight": "700",
        gap: "12px",
      });
      const confirm = page.getByRole("button", { name: "Start now", exact: true });
      await expect(confirm).toBeVisible({ timeout: 3000 });
      await expect(drafting).toHaveCount(0);
      // The plan card: tier, query, Agents / Cost / Time, three numbered steps, Start now, Change brief.
      const card = confirm.locator("xpath=ancestor::*[.//ol][1]");
      const text = await card.innerText();
      expect(text).toMatch(/VILLAGE/);
      expect(text).toContain("Compare three suppliers");
      expect(text.replace(/\s+/g, " ")).toContain("Agents 2");
      expect(text.replace(/\s+/g, " ")).toContain("Cost about £0.60");
      expect(text.replace(/\s+/g, " ")).toContain("Time about 6 min");
      await expect(card.locator("ol > li")).toHaveCount(3);
      expect((await card.locator("ol > li").nth(1).innerText()).replace(/\s+/g, " ")).toBe(
        "2 Do the work with 2 agents",
      );
      const c = await facts(confirm, [
        "height",
        "padding",
        "border-top-left-radius",
        "background-color",
        "color",
        "font-size",
        "font-weight",
      ]);
      expectFacts("Start now", c, {
        padding: "0px 22px",
        "border-top-left-radius": "14px",
        "background-color": TOKENS.day.hero,
        color: "rgb(255, 255, 255)",
        "font-size": "15px",
        "font-weight": "800",
      });
      near("Start now height", Number(c.h), 46);
      const change = await facts(page.getByRole("button", { name: "Change brief", exact: true }), [
        "padding",
        "border-top-left-radius",
        "border-top-width",
        "border-top-color",
        "background-color",
        "font-size",
        "font-weight",
      ]);
      expectFacts("Change brief", change, {
        padding: "0px 18px",
        "border-top-left-radius": "12px",
        "border-top-width": "1px",
        "border-top-color": "rgba(31, 29, 43, 0.12)",
        "background-color": "rgb(255, 255, 255)",
        "font-size": "14px",
        "font-weight": "800",
      });
      near("Change brief height", Number(change.h), 40);
      const cardF = await facts(card, [
        "padding",
        "border-top-left-radius",
        "background-color",
        "border-top-color",
        "gap",
        "display",
      ]);
      expectFacts("plan card", cardF, {
        padding: "18px 18px 18px 22px",
        "border-top-left-radius": "24px",
        "background-color": TOKENS.day.pop,
        "border-top-color": TOKENS.day.line2,
        gap: "20px",
        display: "grid",
      });
      // Change brief: back to idle with the text kept.
      await page.getByRole("button", { name: "Change brief", exact: true }).click();
      await expect(input(page)).toHaveValue("Compare three suppliers");
      await expect(confirm).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: "Draft a reply to Northline", exact: true }),
      ).toBeVisible();
      // Start again, confirm: the toast is the store's, its action opens the new world.
      await start(page).click();
      await expect(confirm).toBeVisible({ timeout: 3000 });
      await confirm.click();
      const toast = page
        .getByRole("status")
        .filter({ hasText: "Started “Compare three suppliers”" });
      await expect(toast).toBeVisible();
      await expect(input(page)).toHaveValue("");
      await toast.getByRole("button", { name: "Open" }).click();
      await expect(page).toHaveURL(/\/world\/new1$/);
      await expect(page.getByTestId("park-page-world")).toHaveAttribute("data-world-id", "new1");
      expect(problems).toEqual([]);
    });

    test(`WEB_4_e2e_${sizeName}_the_other_sizes_change_start_hint_chips_and_the_plan`, async ({
      page,
    }) => {
      test.setTimeout(60_000);
      const problems = await openHome(page, "day");
      await size(page).getByText("Routine", { exact: true }).click();
      await expect(page.getByRole("button", { name: "Set up routine", exact: true })).toBeVisible();
      await expect(
        page.getByText("You approve the first run. After that it runs on its own."),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Weekly invoice match", exact: true }),
      ).toBeVisible();
      await page.getByRole("button", { name: "Set up routine", exact: true }).click();
      await expect(
        page.getByRole("status").filter({
          hasText: "Tilo is drafting a town for “Every Monday, match invoices to purchase orders”",
        }),
      ).toBeVisible();
      await expect(page.getByRole("button", { name: "Schedule it", exact: true })).toBeVisible({
        timeout: 3000,
      });
      await expect(page.getByText("first run tomorrow 08:00")).toBeVisible();
      await expect(page.getByText("Run once tomorrow at 08:00 for your approval")).toBeVisible();
      await size(page).getByText("Workspace", { exact: true }).click();
      await expect(page.getByRole("button", { name: "Plan project", exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Plan project", exact: true }).click();
      await expect(page.getByRole("button", { name: "Draft the city", exact: true })).toBeVisible({
        timeout: 3000,
      });
      await expect(page.getByText("£400 budget to start")).toBeVisible();
      expect(problems).toEqual([]);
    });

    test(`WEB_4_e2e_${sizeName}_Review_opens_the_K1_world`, async ({ page }) => {
      const problems = await openHome(page, "day");
      await pill(page).click();
      await expect(page).toHaveURL(/\/world\/k1$/);
      await expect(page.getByTestId("park-page-world")).toHaveAttribute("data-world-id", "k1");
      expect(problems).toEqual([]);
    });

    test(`WEB_4_e2e_${sizeName}_Enter_in_the_input_starts_and_Tab_shows_the_focus_ring_on_Start`, async ({
      page,
    }) => {
      await openHome(page, "day");
      await input(page).focus();
      await page.keyboard.press("Tab");
      await expect(start(page)).toBeFocused();
      const ring = await start(page).evaluate((el) => {
        const s = getComputedStyle(el);
        return {
          outlineStyle: s.outlineStyle,
          outlineWidth: s.outlineWidth,
          outlineColor: s.outlineColor,
          outlineOffset: s.outlineOffset,
        };
      });
      expect(ring).toEqual(RING);
      await input(page).fill("Daily inbox triage");
      await input(page).press("Enter");
      await expect(page.getByRole("button", { name: "Start now", exact: true })).toBeVisible({
        timeout: 3000,
      });
    });
  });
}

test.describe("park home at 1440x900: the links of the Today panel", () => {
  test.use({ viewport: DESKTOP });

  const LINKS: [string, (p: Page) => Locator, RegExp][] = [
    ["a live row", (p) => row(p, "Onboard 12 new hires"), /\/world\/hires$/],
    ["All worlds", (p) => today(p).getByText("All worlds", { exact: true }), /\/worlds$/],
    ["Agenda", (p) => today(p).getByText("Agenda", { exact: true }), /\/agenda$/],
    [
      "an up-next row",
      (p) => today(p).getByRole("button", { name: /Supplier sync · Northline/ }),
      /\/agenda$/,
    ],
    [
      "September spend",
      (p) => today(p).getByRole("button", { name: /September spend/ }),
      /\/ledger$/,
    ],
  ];
  for (const [label, target, url] of LINKS) {
    test(`WEB_4_e2e_desktop_link_${label.replaceAll(" ", "_")}_navigates`, async ({ page }) => {
      const problems = await openHome(page, "day");
      await target(page).click();
      await expect(page).toHaveURL(url);
      expect(problems).toEqual([]);
    });
  }

  test("WEB_4_e2e_desktop_every_panel_is_visible_and_the_page_has_one_main_and_one_h1", async ({
    page,
  }) => {
    await openHome(page, "day");
    await expect(hero(page)).toBeVisible();
    await expect(today(page)).toBeVisible();
    await expect(input(page)).toBeVisible();
    await expect(page.getByRole("main")).toHaveCount(1);
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    // the shell owns that chip (nav); the page itself renders none
    await expect(page.getByTestId("park-page-home").getByText(/sample data/i)).toHaveCount(0);
  });
});

test.describe("park home at 390x844: what drops out", () => {
  test.use({ viewport: MOBILE });

  test("WEB_4_e2e_mobile_the_Today_panel_is_not_drawn_under_1180", async ({ page }) => {
    await openHome(page, "day");
    await expect(today(page)).toHaveCount(0);
    await expect(hero(page)).toBeVisible();
    await expect(input(page)).toBeVisible();
    await expect(start(page)).toBeVisible();
  });
});
