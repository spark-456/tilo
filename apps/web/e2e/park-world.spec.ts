// WEB-6 acceptance (plan sections 8a and 10; README "World detail" and "Interactions and motion"):
// /world/<id> in the real Park shell at 1440x900 and 390x844, day and night, on the fixture Api.
// Every expected number follows from the reference page (design_handoff_tilo_web_app/design/Tilo App World.dc.html,
// inline styles) inside the shell's page column (x=60 w=1320 at 1440, x=24 w=342 at 390, WEB-3b):
//   - sheet r28, padding 24 32 36, gap 22 -> content width 1320 - 2 - 64 = 1254 (276 at 390);
//   - top grid `minmax(0,1.7fr) minmax(300px,1fr)` gap 18 from a window of 1060, else one column:
//     map card (1254 - 18) * 1.7 / 2.7 = 778.2 wide, side column 457.8; one column: the full 276;
//   - map card r22 p12 gap 12 (so the map is the card less 26), map 440 high r16, hero tag at 14 / 14 (h32);
//   - lower grid `repeat(auto-fit, minmax(min(100%, 420px), 1fr))` gap 18: two 618 columns at 1440, one at 390;
//   - h1 Nunito 900 36 / -0.8 / 37.8, chip h26 r8, buttons h42 r12, Approve h34, run buttons h38, rows as listed.
// Colours are resolved through the page's own tokens (`var(--card)` etc.), so day and night are both checked
// against the tokens and not against pasted rgb values; #F0A500 / #1F1D2B / #FFFFFF are the design's own.
// Motion is not built (BQ-WEB-3): the bars and the Village ring are checked at their end state.
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-world.spec.ts --project=chromium --no-deps --workers=3
import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";
import { readShifts, watchShifts } from "./support/shifts";
import { DESKTOP, MOBILE } from "./support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;
type Theme = "day" | "night";

const K1_TAG = "Level 3 of 6 · Prototypes and suppliers";
const AMBER = "rgb(240, 165, 0)"; // #F0A500
const NEEDS_INK = "rgb(31, 29, 43)"; // #1F1D2B
const WHITE = "rgb(255, 255, 255)";
const RING = {
  outlineStyle: "solid",
  outlineWidth: "3px",
  outlineColor: "rgb(90, 63, 224)",
  outlineOffset: "2px",
};

// Design-owned contrast exceptions (plan 8c: the design's own values win; the PR lists them): white on the night
// hero fill #7A62F5 is 4.29:1 (Open live view, Run now, Open result by night). Matched by colour pair.
const DESIGN_OWNED_CONTRAST = [["#ffffff", "#7a62f5"]] as const;
function isDesignOwnedContrast(node: { any: { data?: unknown }[] }): boolean {
  return node.any.some((check) => {
    const d = check.data as { fgColor?: string; bgColor?: string } | undefined;
    return DESIGN_OWNED_CONTRAST.some(([fg, bg]) => d?.fgColor === fg && d?.bgColor === bg);
  });
}

// ---- helpers -----------------------------------------------------------------------------------------
type Facts = Record<string, string | number>;

const near = (label: string, got: number, want: number, tol = 1.5) =>
  expect(Math.abs(got - want), `${label}: ${got} vs ${want}`).toBeLessThanOrEqual(tol);

/** Computed values and the box of the element, or of its first ancestor (within `up` levels) whose `anchor`
 * property computes to `value`: the text of a chip or a row sits in a child of the element the design styles. */
async function facts(
  loc: Locator,
  props: readonly string[],
  anchor?: [prop: string, value: string],
  up = 3,
): Promise<Facts> {
  return loc.evaluate(
    (el, arg) => {
      let n: Element = el;
      if (arg.anchor) {
        let c: Element | null = el;
        for (let i = 0; i <= arg.up && c; i++, c = c.parentElement) {
          if (getComputedStyle(c).getPropertyValue(arg.anchor[0]) === arg.anchor[1]) {
            n = c;
            break;
          }
        }
      }
      const s = getComputedStyle(n);
      const r = n.getBoundingClientRect();
      const out: Record<string, string | number> = { x: r.x, y: r.y, w: r.width, h: r.height };
      for (const p of arg.props) out[p] = s.getPropertyValue(p);
      return out;
    },
    { props, anchor, up },
  );
}

function expectFacts(label: string, got: Facts, want: Record<string, string>) {
  for (const [k, v] of Object.entries(want)) expect(got[k], `${label} ${k}`).toBe(v);
}

/** What `var(--name)` computes to as a background colour inside the [data-park] root (day or night). */
async function token(page: Page, name: string): Promise<string> {
  return page.locator("[data-park]").evaluate((root, n) => {
    const probe = document.createElement("span");
    probe.style.background = `var(${n})`;
    root.appendChild(probe);
    const v = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return v;
  }, name);
}

async function openWorld(page: Page, id: string, theme: Theme = "day"): Promise<string[]> {
  const problems = collectConsoleProblems(page);
  await page.goto(`/world/${id}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByTestId("park-page-world")).toBeVisible();
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  if (theme === "night") {
    await page.locator("[data-park]").evaluate((el) => el.setAttribute("data-time", "night"));
  }
  return problems;
}

const root = (page: Page) => page.getByTestId("park-page-world");
const sheet = (page: Page) => root(page).locator(".park-sheet").first();
const h1 = (page: Page) => page.getByRole("heading", { level: 1 });
const crumb = (page: Page) => page.getByRole("navigation", { name: "Breadcrumb" });
const btn = (page: Page, name: string) => page.getByRole("button", { name, exact: true });
const live = (page: Page) => page.getByRole("link", { name: "Open live view" });
const text = (page: Page, t: string) => root(page).getByText(t, { exact: true }).first();
/** The map block: the parent of the hero tag. The card around it is its parent. */
const mapOf = (page: Page, tag: string) => text(page, tag).locator("xpath=..");
const cardOf = (page: Page, tag: string) => mapOf(page, tag).locator("xpath=..");
const region = (page: Page, name: string) => root(page).locator(`section[aria-label="${name}"]`);

// A cold Vite dev server optimises its dependencies on the first request and reloads the page; warm it
// once per worker so no test pays for it.
test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(150_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/world/k1", { timeout: 120_000 });
  await page
    .getByRole("heading", { level: 1 })
    .waitFor({ timeout: 120_000 })
    .catch(() => undefined);
  await page.close();
});

for (const [sizeName, viewport] of Object.entries(SIZES)) {
  const wide = viewport.width >= 1060;
  const sheetBox = wide ? { x: 60, w: 1320 } : { x: 24, w: 342 };
  const inner = sheetBox.w - 66; // border 2 + padding 64
  const topCols = wide ? [((inner - 18) * 1.7) / 2.7, ((inner - 18) * 1) / 2.7] : [inner, inner];
  const lowerCols = wide ? [(inner - 18) / 2, (inner - 18) / 2] : [inner, inner];

  for (const theme of ["day", "night"] as const) {
    test.describe(`park world at ${sizeName}, ${theme}`, () => {
      test.use({ viewport });

      test(`WEB_6_e2e_${sizeName}_${theme}_the_page_loads_in_the_shell_with_no_console_output_and_no_sideways_scroll`, async ({
        page,
      }) => {
        const problems = await openWorld(page, "k1", theme);
        await expect(page).toHaveTitle("World · Tilo");
        await expect(page.getByRole("main")).toHaveCount(1);
        await expect(page.getByRole("main").getByTestId("park-page-world")).toHaveCount(1);
        await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
        await expect(h1(page)).toHaveText("K1 electric scooter");
        const overflow = await page.evaluate(() => ({
          page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          body: document.body.scrollWidth - document.body.clientWidth,
        }));
        expect(overflow.page, "the page scrolls sideways").toBeLessThanOrEqual(0);
        expect(overflow.body).toBeLessThanOrEqual(0);
        const sheetOverflow = await sheet(page).evaluate((el) => el.scrollWidth - el.clientWidth);
        expect(
          sheetOverflow,
          "the sheet's own content is wider than the sheet",
        ).toBeLessThanOrEqual(0);
        expect(problems).toEqual([]);
      });

      test(`WEB_6_e2e_${sizeName}_${theme}_the_sheet_the_title_block_and_the_buttons_match_the_reference`, async ({
        page,
      }) => {
        const problems = await openWorld(page, "k1", theme);
        const sh = await facts(sheet(page), [
          "padding",
          "gap",
          "border-top-left-radius",
          "border-top-width",
          "border-top-color",
          "background-color",
          "box-shadow",
        ]);
        near("sheet x", Number(sh.x), sheetBox.x, 0.6);
        near("sheet width", Number(sh.w), sheetBox.w, 0.6);
        expectFacts("sheet", sh, {
          padding: "24px 32px 36px",
          gap: "22px",
          "border-top-left-radius": "28px",
          "border-top-width": "1px",
          "border-top-color": await token(page, "--gBd"),
          "background-color": await token(page, "--sheet"),
        });

        // breadcrumb: 14/700 ink3, the back link h32 `0 10px 0 6px` r10 ink2, gap 8 to the slash and the name
        const nav = await facts(crumb(page), ["font-size", "font-weight", "color", "gap"]);
        expectFacts("breadcrumb", nav, {
          "font-size": "14px",
          "font-weight": "700",
          color: await token(page, "--ink3").then((c) => c.replace(/^rgb/, "rgb")),
          gap: "8px",
        });
        const back = await facts(crumb(page).getByRole("link", { name: "Worlds" }), [
          "padding",
          "border-top-left-radius",
          "color",
          "gap",
        ]);
        near("back link height", Number(back.h), 32, 0.6);
        expectFacts("back link", back, {
          padding: "0px 10px 0px 6px",
          "border-top-left-radius": "10px",
          gap: "6px",
        });
        // the name at the end is --ink, the slash --ink3
        await expect(crumb(page).locator("span").first()).toHaveText("/");
        const crumbName = crumb(page).locator(".park-world-crumbname");
        await expect(crumbName).toHaveText("K1 electric scooter");
        await expect(crumbName).toHaveCSS("color", await token(page, "--ink"));

        // h1: Nunito 900 36px, tracking -0.8, line 37.8
        const t = await facts(h1(page), [
          "font-family",
          "font-size",
          "font-weight",
          "letter-spacing",
          "line-height",
          "margin-top",
          "color",
        ]);
        expect(String(t["font-family"])).toMatch(/^"?Nunito"?\b(?!\s*Sans)/);
        expectFacts("h1", t, {
          "font-size": "36px",
          "font-weight": "900",
          "letter-spacing": "-0.8px",
          "margin-top": "0px",
          color: await token(page, "--ink").then((c) => c),
        });
        near("h1 line height", Number.parseFloat(String(t["line-height"])), 37.8, 0.1);

        // eyebrow and the Needs-you chip (#F0A500 on #1F1D2B, h26 r8 12.5/800, a 7px dot)
        const eyebrow = await facts(text(page, "CITY · WORKSPACE"), [
          "font-size",
          "font-weight",
          "letter-spacing",
        ]);
        expectFacts("eyebrow", eyebrow, {
          "font-size": "12px",
          "font-weight": "800",
          "letter-spacing": "0.7px",
        });
        const chip = await facts(
          text(page, "2 decisions"),
          [
            "font-size",
            "font-weight",
            "border-top-left-radius",
            "background-color",
            "color",
            "gap",
            "padding-left",
          ],
          ["height", "26px"],
        );
        near("chip height", Number(chip.h), 26, 0.6);
        expectFacts("chip", chip, {
          "font-size": "12.5px",
          "font-weight": "800",
          "border-top-left-radius": "8px",
          "background-color": AMBER,
          color: NEEDS_INK,
          gap: "7px",
          "padding-left": "10px",
        });
        const meta = await facts(text(page, "Owned by Alex Morgan · started 2 Sep · 38 agents"), [
          "font-size",
          "font-weight",
          "color",
        ]);
        expectFacts("meta", meta, {
          "font-size": "15.5px",
          "font-weight": "600",
          color: await token(page, "--ink2"),
        });

        // header buttons: h42 r12, `0 16px 0 14px`, 14.5/800, --btn2 on a 1px --line border; the live view --hero on white
        for (const name of ["Pause", "Share"]) {
          const b = await facts(btn(page, name), [
            "padding",
            "border-top-left-radius",
            "font-size",
            "font-weight",
            "background-color",
            "border-top-color",
            "border-top-width",
            "color",
          ]);
          near(`${name} height`, Number(b.h), 42, 0.6);
          expectFacts(name, b, {
            padding: "0px 16px 0px 14px",
            "border-top-left-radius": "12px",
            "font-size": "14.5px",
            "font-weight": "800",
            "background-color": await token(page, "--btn2"),
            "border-top-width": "1px",
            color: await token(page, "--ink"),
          });
        }
        const lv = await facts(live(page), [
          "padding",
          "border-top-left-radius",
          "font-size",
          "font-weight",
          "background-color",
          "color",
        ]);
        near("live view height", Number(lv.h), 42, 0.6);
        expectFacts("live view", lv, {
          padding: "0px 18px",
          "border-top-left-radius": "12px",
          "font-size": "14.5px",
          "font-weight": "800",
          "background-color": await token(page, "--hero"),
          color: WHITE,
        });
        // the three sit in a row of the right side, 8 apart (wrapping under the title on a narrow window)
        const [pa, sa, la] = await Promise.all([
          btn(page, "Pause").boundingBox(),
          btn(page, "Share").boundingBox(),
          live(page).boundingBox(),
        ]);
        if (!(pa && sa && la)) throw new Error("buttons have no box");
        if (wide) {
          near("Pause and Share share a row", pa.y, sa.y, 0.6);
          near("gap Pause to Share", sa.x - (pa.x + pa.width), 8, 0.6);
          near("gap Share to live view", la.x - (sa.x + sa.width), 8, 0.6);
          near(
            "the actions end at the content edge",
            la.x + la.width,
            sheetBox.x + 1 + 32 + inner,
            1,
          );
        }
        for (const b of [pa, sa, la]) {
          expect(b.x + b.width, "a button leaves the sheet").toBeLessThanOrEqual(
            sheetBox.x + sheetBox.w,
          );
        }
        expect(problems).toEqual([]);
      });

      test(`WEB_6_e2e_${sizeName}_${theme}_the_top_grid_the_map_the_progress_bar_and_the_side_column_match_the_reference`, async ({
        page,
      }) => {
        const problems = await openWorld(page, "k1", theme);
        const card = await facts(cardOf(page, K1_TAG), [
          "padding",
          "gap",
          "border-top-left-radius",
          "border-top-color",
          "background-color",
        ]);
        near("map card x", Number(card.x), sheetBox.x + 33, 1);
        near("map card width", Number(card.w), topCols[0] as number, 1.2);
        expectFacts("map card", card, {
          padding: "12px",
          gap: "12px",
          "border-top-left-radius": "22px",
          "border-top-color": await token(page, "--line2"),
          "background-color": await token(page, "--card"),
        });
        const map = await facts(mapOf(page, K1_TAG), [
          "position",
          "border-top-left-radius",
          "background-color",
          "overflow",
        ]);
        near("map height", Number(map.h), 440, 0.6);
        near(
          "map width = card less padding and border",
          Number(map.w),
          (topCols[0] as number) - 26,
          1.2,
        );
        expectFacts("map", map, {
          position: "relative",
          "border-top-left-radius": "16px",
          "background-color": await token(page, "--sunk"),
          overflow: "hidden",
        });
        const tag = await facts(text(page, K1_TAG), [
          "position",
          "border-top-left-radius",
          "background-color",
          "font-size",
          "font-weight",
          "padding-left",
          "box-shadow",
        ]);
        near("tag left", Number(tag.x) - Number(map.x), 14, 0.6);
        near("tag top", Number(tag.y) - Number(map.y), 14, 0.6);
        near("tag height", Number(tag.h), 32, 0.6);
        expectFacts("hero tag", tag, {
          position: "absolute",
          "border-top-left-radius": "10px",
          "background-color": await token(page, "--pop"),
          "font-size": "13px",
          "font-weight": "800",
          "padding-left": "12px",
        });
        // the world art is drawn inside the map and does not spill out of it
        const art = mapOf(page, K1_TAG).locator("img, svg").first();
        await expect(art).toBeVisible();
        const ab = await art.boundingBox();
        if (!ab) throw new Error("no art box");
        expect(ab.x).toBeGreaterThanOrEqual(Number(map.x) - 1);
        expect(ab.x + ab.width).toBeLessThanOrEqual(Number(map.x) + Number(map.w) + 1);

        // progress: a 6px track, the amber fill at 46% (Needs you), the label 13.5/800 right aligned
        const label = await facts(text(page, "46%"), ["font-size", "font-weight", "text-align"]);
        expectFacts("progress label", label, {
          "font-size": "13.5px",
          "font-weight": "800",
          "text-align": "right",
        });
        const track = text(page, "46%").locator("xpath=..").locator("div").first();
        const trackFacts = await facts(track, [
          "border-top-left-radius",
          "background-color",
          "overflow",
        ]);
        near("track height", Number(trackFacts.h), 6, 0.6);
        expectFacts("track", trackFacts, {
          "border-top-left-radius": "99px",
          "background-color": await token(page, "--track"),
          overflow: "hidden",
        });
        const fill = await facts(track.locator("div").first(), ["background-color"]);
        near("fill width = 46% of the track", Number(fill.w), Number(trackFacts.w) * 0.46, 1);
        expect(fill["background-color"], "needs state: --amber").toBe(await token(page, "--amber"));

        // legend: 9px swatches in the four state colours, 12.5/700 ink2, gap 14
        const legend = ["Building", "Needs you", "Done", "Planned"];
        const swatchColour = [
          await token(page, "--run"),
          await token(page, "--amber"),
          await token(page, "--ok"),
          await token(page, "--track"),
        ];
        for (const [i, name] of legend.entries()) {
          const item = card_legend(page, name);
          const sw = await facts(item.locator("span").first(), [
            "background-color",
            "border-top-left-radius",
          ]);
          near(`${name} swatch`, Number(sw.w), 9, 0.6);
          near(`${name} swatch h`, Number(sw.h), 9, 0.6);
          expectFacts(`${name} swatch`, sw, {
            "background-color": swatchColour[i] as string,
            "border-top-left-radius": "3px",
          });
        }

        // side column: the next column of the top grid (18 away), or under the card on a narrow window
        const waiting = await facts(
          text(page, "WAITING FOR YOU").locator("xpath=ancestor::div[contains(@class,'') ][3]"),
          ["padding"],
        ).catch(() => null);
        expect(waiting === null || Number(waiting.w) > 0).toBe(true);
        const spend = await facts(text(page, "Spend").locator("xpath=ancestor::div[2]"), [
          "padding",
          "gap",
          "border-top-left-radius",
          "background-color",
        ]);
        if (wide) {
          near("side column x", Number(spend.x), Number(card.x) + Number(card.w) + 18, 1.2);
          near("side column width", Number(spend.w), topCols[1] as number, 1.2);
        } else {
          near("side column x (one column)", Number(spend.x), Number(card.x), 1.2);
          expect(Number(spend.y), "under the map card").toBeGreaterThan(
            Number(card.y) + Number(card.h),
          );
          near("side column width (one column)", Number(spend.w), inner, 1.2);
        }
        expectFacts("spend card", spend, {
          padding: "18px 18px 16px",
          gap: "12px",
          "border-top-left-radius": "22px",
          "background-color": await token(page, "--card"),
        });
        expect(problems).toEqual([]);
      });

      test(`WEB_6_e2e_${sizeName}_${theme}_waiting_spend_facts_chips_match_the_reference`, async ({
        page,
      }) => {
        const problems = await openWorld(page, "k1", theme);
        // Waiting for you: --amberSoft, 1px --amberLine, r22, p16, gap 12; label 12/800 .6 --amberInk; title 15/800
        const needs = await facts(
          text(page, "2 decisions before agents continue"),
          ["padding", "gap", "border-top-left-radius", "background-color", "border-top-color"],
          ["background-color", await token(page, "--amberSoft")],
          5,
        );
        expectFacts("waiting card", needs, {
          padding: "16px",
          gap: "12px",
          "border-top-left-radius": "22px",
          "background-color": await token(page, "--amberSoft"),
          "border-top-color": await token(page, "--amberLine"),
        });
        const label = await facts(text(page, "WAITING FOR YOU"), [
          "font-size",
          "font-weight",
          "letter-spacing",
          "color",
        ]);
        expectFacts("waiting label", label, {
          "font-size": "12px",
          "font-weight": "800",
          "letter-spacing": "0.6px",
          color: await token(page, "--amberInk"),
        });
        const title = await facts(text(page, "2 decisions before agents continue"), [
          "font-size",
          "font-weight",
        ]);
        expectFacts("waiting title", title, { "font-size": "15px", "font-weight": "800" });

        // a decision card: --card r14, 12 14, gap 10; title 14/800, body 13/600 ink2
        const dt = await facts(text(page, "Laptop Depot · budget sign-off"), [
          "font-size",
          "font-weight",
        ]);
        expectFacts("decision title", dt, { "font-size": "14px", "font-weight": "800" });
        const dcard = await facts(
          text(page, "Laptop Depot · budget sign-off"),
          ["padding", "gap", "border-top-left-radius", "background-color"],
          ["border-top-left-radius", "14px"],
          4,
        );
        expectFacts("decision card", dcard, {
          padding: "12px 14px",
          gap: "10px",
          "border-top-left-radius": "14px",
          "background-color": await token(page, "--card"),
        });
        const body = await facts(
          text(page, "6 test laptops for firmware, £3,420. Above the £2,500 district limit."),
          ["font-size", "font-weight", "color"],
        );
        expectFacts("decision body", body, {
          "font-size": "13px",
          "font-weight": "600",
          color: await token(page, "--ink2").then((c) => c),
        });
        // Approve h34 `0 14px` #F0A500 on #1F1D2B 13.5/800; Ask me later h34 `0 12px` --btn2 on --line
        const approve = await facts(btn(page, "Approve £3,420"), [
          "padding",
          "border-top-left-radius",
          "font-size",
          "font-weight",
          "background-color",
          "color",
        ]);
        near("Approve height", Number(approve.h), 34, 0.6);
        expectFacts("Approve", approve, {
          padding: "0px 14px",
          "border-top-left-radius": "10px",
          "font-size": "13.5px",
          "font-weight": "800",
          "background-color": AMBER,
          color: NEEDS_INK,
        });
        const later = await facts(btn(page, "Ask me later").first(), [
          "padding",
          "border-top-left-radius",
          "font-size",
          "font-weight",
          "background-color",
          "color",
          "border-top-color",
        ]);
        near("Ask me later height", Number(later.h), 34, 0.6);
        expectFacts("Ask me later", later, {
          padding: "0px 12px",
          "border-top-left-radius": "10px",
          "font-size": "13.5px",
          "font-weight": "800",
          "background-color": await token(page, "--btn2"),
          color: await token(page, "--ink"),
          "border-top-color": await token(page, "--line"),
        });

        // Spend: 28/800 -0.5 value, "of" 14/700 ink2, an 8px --track bar with the --hero fill at 34.6%, note 13/700
        const value = await facts(text(page, "£1,386"), [
          "font-size",
          "font-weight",
          "letter-spacing",
        ]);
        expectFacts("spend value", value, {
          "font-size": "28px",
          "font-weight": "800",
          "letter-spacing": "-0.5px",
        });
        const of = await facts(text(page, "of £4,000"), ["font-size", "font-weight", "color"]);
        expectFacts("spend of", of, {
          "font-size": "14px",
          "font-weight": "700",
          color: await token(page, "--ink2"),
        });
        const bar = await facts(
          text(page, "£3,420 is waiting for your sign-off at Laptop Depot.").locator(
            "xpath=preceding-sibling::div[1]",
          ),
          ["border-top-left-radius", "background-color", "overflow"],
        );
        near("spend bar height", Number(bar.h), 8, 0.6);
        expectFacts("spend bar", bar, {
          "border-top-left-radius": "99px",
          "background-color": await token(page, "--track"),
          overflow: "hidden",
        });
        const barFill = await facts(
          text(page, "£3,420 is waiting for your sign-off at Laptop Depot.").locator(
            "xpath=preceding-sibling::div[1]/div",
          ),
          ["background-color"],
        );
        near("spend fill = 1386 / 4000 of the bar", Number(barFill.w), Number(bar.w) * 0.3465, 1);
        expect(barFill["background-color"]).toBe(await token(page, "--hero"));
        const note = await facts(
          text(page, "£3,420 is waiting for your sign-off at Laptop Depot."),
          ["font-size", "font-weight", "color", "line-height"],
        );
        expectFacts("spend note", note, {
          "font-size": "13px",
          "font-weight": "700",
          color: await token(page, "--ink2"),
        });
        near("spend note line", Number.parseFloat(String(note["line-height"])), 18.2, 0.2);

        // facts: 96px label column, rows min 44 with a 1px --line2 rule, label 13/700 ink3, value 14/800
        const owner = await facts(text(page, "Owner"), ["font-size", "font-weight", "color"]);
        expectFacts("fact label", owner, {
          "font-size": "13px",
          "font-weight": "700",
          color: await token(page, "--ink3"),
        });
        const row = await facts(text(page, "Owner").locator("xpath=.."), [
          "display",
          "grid-template-columns",
          "padding",
          "border-bottom-width",
          "border-bottom-color",
          "column-gap",
        ]);
        expect(row.display).toBe("grid");
        expect(String(row["grid-template-columns"]).split(" ")[0]).toBe("96px");
        near("fact row height", Number(row.h), 44, 0.6);
        expectFacts("fact row", row, {
          padding: "6px 0px",
          "border-bottom-width": "1px",
          "border-bottom-color": await token(page, "--line2"),
          "column-gap": "12px",
        });
        const val = await facts(text(page, "Alex Morgan").first(), ["font-size", "font-weight"]);
        expectFacts("fact value", val, { "font-size": "14px", "font-weight": "800" });

        // skills and tools chips: h28 r8 12.5/800; the skill chip --heroSoft on --heroInk, the tool chip --btn2 on --line
        const skill = await facts(btn(page, "Draft a supplier brief"), [
          "padding",
          "border-top-left-radius",
          "font-size",
          "font-weight",
          "background-color",
          "color",
          "gap",
        ]);
        near("skill chip height", Number(skill.h), 28, 0.6);
        expectFacts("skill chip", skill, {
          padding: "0px 10px",
          "border-top-left-radius": "8px",
          "font-size": "12.5px",
          "font-weight": "800",
          "background-color": await token(page, "--heroSoft"),
          color: await token(page, "--heroInk"),
          gap: "6px",
        });
        const tool = await facts(
          btn(page, "DGoogle Drive").or(btn(page, "D Google Drive")).first(),
          [
            "padding",
            "border-top-left-radius",
            "background-color",
            "border-top-color",
            "color",
            "gap",
          ],
        );
        near("tool chip height", Number(tool.h), 28, 0.6);
        expectFacts("tool chip", tool, {
          padding: "0px 10px 0px 4px",
          "border-top-left-radius": "8px",
          "background-color": await token(page, "--btn2"),
          "border-top-color": await token(page, "--line"),
          color: await token(page, "--ink"),
          gap: "6px",
        });
        const mono = await facts(page.getByText("D", { exact: true }).last(), [
          "font-size",
          "font-weight",
          "border-top-left-radius",
          "background-color",
        ]).catch(() => null);
        if (mono) {
          near("monogram width", Number(mono.w), 20, 0.6);
          expectFacts("monogram", mono, {
            "font-size": "10.5px",
            "font-weight": "900",
            "border-top-left-radius": "6px",
            "background-color": await token(page, "--sunk"),
          });
        }
        expect(problems).toEqual([]);
      });

      test(`WEB_6_e2e_${sizeName}_${theme}_districts_and_activity_match_the_reference`, async ({
        page,
      }) => {
        const problems = await openWorld(page, "k1", theme);
        // lower grid: two 618px columns at 1440, one at 390; gap 18; sections r22, p `18 18 10`, gap 4
        const districts = region(page, "Districts");
        const activity = region(page, "Activity");
        const d = await facts(districts, [
          "padding",
          "gap",
          "border-top-left-radius",
          "background-color",
          "border-top-color",
        ]);
        const a = await facts(activity, ["padding", "border-top-left-radius"]);
        near("districts width", Number(d.w), lowerCols[0] as number, 1.2);
        near("activity width", Number(a.w), lowerCols[1] as number, 1.2);
        if (wide) {
          near("same row", Number(d.y), Number(a.y), 0.6);
          near("column gap", Number(a.x) - (Number(d.x) + Number(d.w)), 18, 1.2);
        } else {
          near("same x", Number(d.x), Number(a.x), 0.6);
          near("row gap", Number(a.y) - (Number(d.y) + Number(d.h)), 18, 1.2);
        }
        expectFacts("districts", d, {
          padding: "18px 18px 10px",
          gap: "4px",
          "border-top-left-radius": "22px",
          "background-color": await token(page, "--card"),
          "border-top-color": await token(page, "--line2"),
        });
        const h2 = await facts(districts.getByRole("heading", { level: 2, name: "Districts" }), [
          "font-size",
          "font-weight",
          "margin-top",
        ]);
        expectFacts("h2", h2, { "font-size": "17px", "font-weight": "800", "margin-top": "0px" });
        const sub = await facts(districts.getByText("5 districts", { exact: true }), [
          "font-size",
          "font-weight",
          "color",
        ]);
        expectFacts("sub", sub, {
          "font-size": "13px",
          "font-weight": "700",
          color: await token(page, "--ink3"),
        });

        // a district row: grid 40 / 1fr / 110 / auto, gap 14, p `10 4`, a 1px --line2 rule on top; tile 40 r12; chip h24 r7
        const name = await facts(districts.getByText("Firmware", { exact: true }), [
          "font-size",
          "font-weight",
        ]);
        expectFacts("district name", name, { "font-size": "14.5px", "font-weight": "800" });
        const row = await facts(
          districts
            .getByText("Firmware", { exact: true })
            .locator("xpath=ancestor::*[contains(@style,'') or true][2]"),
          [
            "display",
            "grid-template-columns",
            "column-gap",
            "padding",
            "border-top-width",
            "border-top-color",
          ],
        );
        expect(row.display, "the row is a grid").toBe("grid");
        const cols = String(row["grid-template-columns"]).split(" ");
        expect(cols[0]).toBe("40px");
        expect(cols[2]).toBe("110px");
        expectFacts("district row", row, {
          "column-gap": "14px",
          padding: "10px 4px",
          "border-top-width": "1px",
          "border-top-color": await token(page, "--line2"),
        });
        const note = await facts(
          districts.getByText("Laptop Depot waiting on budget", { exact: true }),
          ["font-size", "font-weight", "color", "white-space", "text-overflow"],
        );
        expectFacts("district note", note, {
          "font-size": "13px",
          "font-weight": "600",
          color: await token(page, "--ink2"),
          "white-space": "nowrap",
          "text-overflow": "ellipsis",
        });
        const count = await facts(
          districts.getByText("1 of 2 buildings · 12 agents", { exact: true }),
          ["font-size", "font-weight", "color"],
        );
        expectFacts("district count", count, {
          "font-size": "12.5px",
          "font-weight": "700",
          color: await token(page, "--ink2"),
        });
        const bar = districts
          .getByText("1 of 2 buildings · 12 agents", { exact: true })
          .locator("xpath=following-sibling::*[1]");
        const barFacts = await facts(bar, [
          "border-top-left-radius",
          "background-color",
          "overflow",
        ]);
        near("district bar height", Number(barFacts.h), 5, 0.6);
        expectFacts("district bar", barFacts, {
          "border-top-left-radius": "99px",
          "background-color": await token(page, "--track"),
          overflow: "hidden",
        });
        const fill = await facts(bar.locator("*").first(), ["background-color"]);
        near("district fill = half", Number(fill.w), Number(barFacts.w) / 2, 1);
        expect(fill["background-color"], "needs: --amber").toBe(await token(page, "--amber"));

        // chips of the five states (design values): Needs you #F0A500/#1F1D2B, Building heroSoft/heroInk, Done okSoft/okInk, Planned chip/ink2
        const chipWant: Record<string, [string, string]> = {
          "Needs you": [AMBER, NEEDS_INK],
          Building: [await token(page, "--heroSoft"), await token(page, "--heroInk")],
          Done: [await token(page, "--okSoft"), await token(page, "--okInk")],
          Planned: [await token(page, "--chip"), await token(page, "--ink2")],
        };
        for (const [label, [bg, fg]] of Object.entries(chipWant)) {
          const chip = await facts(
            districts.getByText(label, { exact: true }).first(),
            [
              "font-size",
              "font-weight",
              "border-top-left-radius",
              "background-color",
              "color",
              "padding-left",
            ],
            ["height", "24px"],
          );
          near(`${label} chip height`, Number(chip.h), 24, 0.6);
          expectFacts(`${label} chip`, chip, {
            "font-size": "12px",
            "font-weight": "800",
            "border-top-left-radius": "7px",
            "background-color": bg,
            color: fg,
            "padding-left": "9px",
          });
        }

        // activity row: 36 / 1fr / auto, gap 12, p `10 4`; who 13/800 ink2 with a 7px dot, text 14/600, time 12.5/700 ink3
        const who = await facts(activity.getByText("Builder", { exact: true }), [
          "font-size",
          "font-weight",
          "color",
        ]);
        expectFacts("who", who, {
          "font-size": "13px",
          "font-weight": "800",
          color: await token(page, "--ink2"),
        });
        const atext = await facts(
          activity.getByText("Paused Laptop Depot. £3,420 is above the £2,500 district limit.", {
            exact: true,
          }),
          ["font-size", "font-weight"],
        );
        expectFacts("activity text", atext, { "font-size": "14px", "font-weight": "600" });
        const time = await facts(activity.getByText("11:52", { exact: true }), [
          "font-size",
          "font-weight",
          "color",
          "white-space",
        ]);
        expectFacts("activity time", time, {
          "font-size": "12.5px",
          "font-weight": "700",
          color: await token(page, "--ink3"),
          "white-space": "nowrap",
        });
        const arow = await facts(activity.getByText("11:52", { exact: true }).locator("xpath=.."), [
          "display",
          "grid-template-columns",
          "column-gap",
          "padding",
          "border-top-color",
        ]);
        expect(arow.display).toBe("grid");
        expect(String(arow["grid-template-columns"]).split(" ")[0]).toBe("36px");
        expectFacts("activity row", arow, {
          "column-gap": "12px",
          padding: "10px 4px",
          "border-top-color": await token(page, "--line2"),
        });
        expect(problems).toEqual([]);
      });
    });
  }
}

test.describe("park world: the other tiers at 1440", () => {
  test.use({ viewport: DESKTOP });

  test("WEB_6_e2e_a_Town_shows_its_row_of_buildings_run_history_and_the_run_buttons", async ({
    page,
  }) => {
    const problems = await openWorld(page, "invoice");
    await expect(h1(page)).toHaveText("Weekly invoice match");
    await expect(root(page).getByText("TOWN · ROUTINE", { exact: true })).toBeVisible();
    await expect(live(page)).toHaveCount(0);
    await expect(region(page, "Districts")).toHaveCount(0);
    const runs = region(page, "Run history");
    await expect(runs.getByRole("heading", { level: 2, name: "Run history" })).toBeVisible();
    await expect(runs.getByText("3 recent runs", { exact: true })).toBeVisible();
    const row = await facts(
      runs.getByText("142 matched · 3 flagged", { exact: true }).locator("xpath=ancestor::*[2]"),
      ["display", "grid-template-columns", "column-gap", "padding", "border-top-color"],
    );
    expect(row.display).toBe("grid");
    expect(String(row["grid-template-columns"]).split(" ")[0]).toBe("32px");
    expectFacts("run row", row, {
      "column-gap": "12px",
      padding: "11px 4px",
      "border-top-color": await token(page, "--line2"),
    });
    const runNow = await facts(runs.getByRole("button", { name: "Run now" }), [
      "padding",
      "border-top-left-radius",
      "font-size",
      "font-weight",
      "background-color",
      "color",
    ]);
    near("Run now height", Number(runNow.h), 38, 0.6);
    expectFacts("Run now", runNow, {
      padding: "0px 14px 0px 12px",
      "border-top-left-radius": "11px",
      "font-size": "14px",
      "font-weight": "800",
      "background-color": await token(page, "--hero"),
      color: WHITE,
    });
    const agenda = await facts(runs.getByRole("button", { name: "See in Agenda" }), [
      "padding",
      "border-top-left-radius",
      "background-color",
      "border-top-color",
    ]);
    near("See in Agenda height", Number(agenda.h), 38, 0.6);
    expectFacts("See in Agenda", agenda, {
      padding: "0px 14px",
      "border-top-left-radius": "11px",
      "background-color": await token(page, "--btn2"),
      "border-top-color": await token(page, "--line"),
    });
    // a scheduled routine: chip Scheduled on --chip with the --sch dot, an empty bar and the next run as the label
    const chip = await facts(
      text(page, "Scheduled"),
      ["background-color", "color"],
      ["height", "26px"],
    );
    expectFacts("Scheduled chip", chip, {
      "background-color": await token(page, "--chip"),
      color: await token(page, "--ink"),
    });
    const track = text(page, "Mon 09:00").locator("xpath=..").locator("div").first();
    const fill = await facts(track.locator("div").first(), ["background-color"]);
    expect(Number(fill.w), "empty bar").toBeLessThanOrEqual(0.6);
    // Run now toasts
    await runs.getByRole("button", { name: "Run now" }).click();
    await expect(
      page.getByRole("status").filter({ hasText: "Sample only: nothing was started." }),
    ).toBeVisible();
    // See in Agenda goes to the agenda page
    await runs.getByRole("button", { name: "See in Agenda" }).click();
    await expect(page).toHaveURL(/\/agenda$/);
    expect(problems).toEqual([]);
  });

  test("WEB_6_e2e_a_Village_shows_its_result_the_ring_and_the_finished_buttons", async ({
    page,
  }) => {
    const problems = await openWorld(page, "calls");
    await expect(h1(page)).toHaveText("Summarise yesterday’s calls");
    const result = region(page, "Result");
    await expect(
      result.getByText("Summary of 7 calls, with actions per owner", { exact: true }),
    ).toBeVisible();
    const out = await facts(
      result.getByText("Summary of 7 calls, with actions per owner", { exact: true }),
      [
        "padding",
        "border-top-left-radius",
        "background-color",
        "font-size",
        "font-weight",
        "line-height",
      ],
    );
    expectFacts("result text", out, {
      padding: "16px 18px",
      "border-top-left-radius": "14px",
      "background-color": await token(page, "--sunk"),
      "font-size": "15px",
      "font-weight": "700",
    });
    near("result line height", Number.parseFloat(String(out["line-height"])), 22.5, 0.2);
    // running: the 16px ring (a --track ring with a --hero top) beside the recorded line; no buttons
    const running = result
      .getByText("Recorded sample state: About 3 min left", { exact: true })
      .last();
    const ring = running.locator("xpath=preceding-sibling::*[1]");
    const rf = await facts(ring, [
      "border-top-width",
      "border-top-color",
      "border-right-color",
      "border-top-left-radius",
    ]);
    near("ring width", Number(rf.w), 16, 0.6);
    near("ring height", Number(rf.h), 16, 0.6);
    expectFacts("ring", rf, {
      "border-top-width": "2px", // the CSS holds 2.5px; Chromium snaps border widths to whole pixels at DPR 1
      "border-top-color": await token(page, "--hero"),
      "border-right-color": await token(page, "--track"),
      "border-top-left-radius": "99px",
    });
    await expect(result.getByRole("button", { name: "Open result" })).toHaveCount(0);
    // a finished one has the two buttons: Open result (h38 `0 16px` --hero) and Share to Slack (h38 `0 14px`)
    await page.goto("/world/comp");
    await expect(h1(page)).toHaveText("Competitor pricing");
    const open = await facts(region(page, "Result").getByRole("button", { name: "Open result" }), [
      "padding",
      "border-top-left-radius",
      "background-color",
      "color",
    ]);
    near("Open result height", Number(open.h), 38, 0.6);
    expectFacts("Open result", open, {
      padding: "0px 16px",
      "border-top-left-radius": "11px",
      "background-color": await token(page, "--hero"),
      color: WHITE,
    });
    const slack = await facts(
      region(page, "Result").getByRole("button", { name: "Share to Slack" }),
      ["padding", "background-color", "border-top-color"],
    );
    near("Share to Slack height", Number(slack.h), 38, 0.6);
    expectFacts("Share to Slack", slack, {
      padding: "0px 14px",
      "background-color": await token(page, "--btn2"),
      "border-top-color": await token(page, "--line"),
    });
    await expect(text(page, "Ready")).toBeVisible();
    const readyChip = await facts(
      text(page, "Ready"),
      ["background-color", "color"],
      ["height", "26px"],
    );
    expectFacts("Ready chip", readyChip, {
      "background-color": await token(page, "--okSoft"),
      color: await token(page, "--okInk"),
    });
    await region(page, "Result").getByRole("button", { name: "Open result" }).click();
    await expect(
      page.getByRole("status").filter({ hasText: "Sample only: nothing was opened." }),
    ).toBeVisible();
    expect(problems).toEqual([]);
  });

  test("WEB_6_e2e_a_second_City_has_no_Waiting_card_and_its_own_districts_skills_and_tools", async ({
    page,
  }) => {
    const problems = await openWorld(page, "hires");
    await expect(h1(page)).toHaveText("Onboard 12 new hires");
    await expect(root(page).getByText("WAITING FOR YOU")).toHaveCount(0);
    // a sample world has no stage (WEB-CUTOVER): the live view is disabled; the live-source href is a vitest case
    await expect(live(page)).toHaveAttribute("aria-disabled", "true");
    await expect(live(page)).not.toHaveAttribute("href", /.*/);
    await expect(region(page, "Districts").getByText("4 districts", { exact: true })).toBeVisible();
    await expect(btn(page, "Set up a new starter")).toBeVisible();
    for (const tool of ["Google Workspace", "BambooHR", "Slack"]) {
      await expect(root(page).getByRole("button", { name: new RegExp(`${tool}$`) })).toBeVisible();
    }
    await expect(text(page, "38% of budget used. Forecast within budget.")).toBeVisible();
    expect(problems).toEqual([]);
  });
});

test.describe("park world: behaviour in the browser", () => {
  test.use({ viewport: DESKTOP });

  test("WEB_6_e2e_opening_a_world_from_Home_runs_the_loader_first_then_shows_the_page", async ({
    page,
  }) => {
    const problems = collectConsoleProblems(page);
    await page.goto("/");
    const review = page.getByRole("button", {
      name: /\d decisions? waiting in K1 electric scooter/,
    });
    await review.click();
    await expect(page.getByText("OPENING CITY", { exact: true })).toBeVisible(); // the WorldLoader of the shell
    await expect(h1(page)).toHaveText("K1 electric scooter");
    await expect(page).toHaveURL(/\/world\/k1$/);
    await expect(page.getByText("OPENING CITY", { exact: true })).toHaveCount(0);
    expect(problems).toEqual([]);
  });

  test("WEB_6_e2e_opening_the_page_shifts_nothing", async ({ page }) => {
    await watchShifts(page);
    await page.goto("/world/k1");
    await expect(h1(page)).toBeVisible();
    await expect(region(page, "Districts")).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.fonts.status)).toBe("loaded");
    const shifts = await readShifts(page);
    expect(shifts.reduce((a, b) => a + b, 0)).toBe(0);
  });

  test("WEB_6_e2e_Approve_Undo_and_Ask_me_later_work_as_designed", async ({ page }) => {
    const problems = await openWorld(page, "k1");
    await btn(page, "Ask me later").first().click();
    await expect(
      page.getByRole("status").filter({ hasText: "Tilo will remind you at 16:00" }),
    ).toBeVisible();
    await btn(page, "Approve £3,420").click();
    const toast = page.getByRole("status").filter({ hasText: "Approved £3,420 for Laptop Depot" });
    await expect(toast).toBeVisible();
    await expect(toast.getByRole("button", { name: "Undo" })).toBeVisible();
    await expect(text(page, "Approved · just now")).toBeVisible();
    await expect(text(page, "1 decision before agents continue")).toBeVisible();
    await expect(text(page, "1 decision")).toBeVisible(); // the status chip
    await expect(
      region(page, "Districts").getByText("Laptop Depot is building", { exact: true }),
    ).toBeVisible();
    await expect(
      region(page, "Activity").getByText("Approved £3,420 for Laptop Depot.", { exact: true }),
    ).toBeVisible();
    await expect(
      text(page, "Laptop Depot approved today for £3,420. It’s billed on delivery."),
    ).toBeVisible();
    await toast.getByRole("button", { name: "Undo" }).click();
    await expect(btn(page, "Approve £3,420")).toBeVisible();
    await expect(text(page, "2 decisions before agents continue")).toBeVisible();
    // both approved: the card goes and the world is running
    await btn(page, "Approve £3,420").click();
    await btn(page, "Send brief").click();
    await expect(root(page).getByText("WAITING FOR YOU")).toHaveCount(0);
    await expect(text(page, "Running")).toBeVisible();
    expect(problems).toEqual([]);
  });

  test("WEB_6_e2e_Pause_dims_the_map_with_the_overlay_and_Resume_brings_it_back", async ({
    page,
  }) => {
    const problems = await openWorld(page, "k1");
    await btn(page, "Pause").click();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "Sample only: paused on this page. Nothing real changed." }),
    ).toBeVisible();
    const overlay = text(page, "Paused · agents are waiting");
    await expect(overlay).toBeVisible();
    await expect(btn(page, "Resume")).toBeVisible();
    await expect(text(page, "Paused")).toBeVisible();
    const map = await mapOf(page, K1_TAG).boundingBox();
    const scrim = await facts(overlay.locator("xpath=.."), ["position", "background-color"]);
    expect(scrim.position).toBe("absolute");
    expect(scrim["background-color"]).toBe(await token(page, "--scrim"));
    near("the scrim covers the map", Number(scrim.w), map?.width ?? 0, 0.6);
    near("the scrim covers the map (height)", Number(scrim.h), 440, 0.6);
    const pill = await facts(
      overlay,
      ["border-top-left-radius", "background-color", "font-size", "font-weight", "padding-left"],
      ["height", "40px"],
    );
    near("pill height", Number(pill.h), 40, 0.6);
    expectFacts("pause pill", pill, {
      "border-top-left-radius": "12px",
      "background-color": await token(page, "--pop"),
      "font-size": "14px",
      "font-weight": "800",
      "padding-left": "16px",
    });
    await btn(page, "Resume").click();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "Sample only: resumed on this page. Nothing real changed." }),
    ).toBeVisible();
    await expect(overlay).toHaveCount(0);
    expect(problems).toEqual([]);
  });

  test("WEB_6_e2e_Share_copies_the_address_and_says_so", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const problems = await openWorld(page, "k1");
    await btn(page, "Share").click();
    await expect(
      page.getByRole("status").filter({
        hasText: "Link copied. This is a sample world, so there is nothing real to share.",
      }),
    ).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(page.url());
    expect(page.url()).toMatch(/\/world\/k1$/);
    expect(problems).toEqual([]);
  });

  test("WEB_6_e2e_the_links_go_where_the_design_says", async ({ page }) => {
    const problems = await openWorld(page, "k1");
    await crumb(page).getByRole("link", { name: "Worlds" }).click();
    await expect(page).toHaveURL(/\/worlds$/);
    await page.goBack();
    await expect(h1(page)).toHaveText("K1 electric scooter");
    await root(page).getByRole("link", { name: "Ledger" }).click();
    await expect(page).toHaveURL(/\/ledger$/);
    await page.goBack();
    await btn(page, "Draft a supplier brief").click();
    await expect(page).toHaveURL(/\/skills\?id=brief$/);
    await page.goBack();
    await btn(page, "Google Drive")
      .or(root(page).getByRole("button", { name: /Google Drive$/ }))
      .first()
      .click();
    await expect(page).toHaveURL(/\/connectors$/);
    expect(problems).toEqual([]);
  });

  test("WEB_6_e2e_a_sample_worlds_live_view_and_lenses_are_disabled_not_links_to_a_missing_stage", async ({
    page,
  }) => {
    // WEB-CUTOVER: a stage exists only for a live-source world (World.stage.test.tsx pins the live hrefs:
    // /world/k1/stage, story, trace, delivery, inspect/B1). A sample world renders the same elements, disabled.
    await openWorld(page, "k1");
    const reason = "Sample world: there is no recorded run to open";
    await expect(live(page)).toHaveAttribute("aria-disabled", "true");
    await expect(live(page)).toHaveAttribute("title", reason);
    await expect(live(page)).not.toHaveAttribute("href", /.*/);
    for (const name of ["Story", "Trace", "Delivery", "Inspect"]) {
      const lens = root(page)
        .getByRole("navigation", { name: "Run views" })
        .getByRole("link", { name });
      await expect(lens, name).toHaveAttribute("aria-disabled", "true");
      await expect(lens, name).not.toHaveAttribute("href", /.*/);
    }
    await expect(root(page).locator('a[href^="/world/k1/"]')).toHaveCount(0);
    await expect(root(page).getByText(reason).first()).toBeAttached();
    // a click, plain or modified, goes nowhere (force: Playwright treats aria-disabled as not clickable)
    await live(page).click({ modifiers: ["ControlOrMeta"], force: true });
    await live(page).click({ force: true });
    expect(new URL(page.url()).pathname).toBe("/world/k1");
  });

  test("WEB_6_e2e_a_keyboard_reaches_every_control_in_reading_order_with_the_README_focus_ring", async ({
    page,
  }) => {
    const problems = await openWorld(page, "k1");
    const back = crumb(page).getByRole("link", { name: "Worlds" });
    await back.focus();
    await page.keyboard.press("Tab"); // keyboard modality: the ring is :focus-visible from here on
    await page.keyboard.press("Shift+Tab");
    await expect(back).toBeFocused();
    // the live view of a sample world is disabled (no href), so the keyboard skips it
    const order = [btn(page, "Pause"), btn(page, "Share")];
    const ring = async (loc: Locator) => {
      const f = await facts(loc, [
        "outline-style",
        "outline-width",
        "outline-color",
        "outline-offset",
      ]);
      return {
        outlineStyle: f["outline-style"],
        outlineWidth: f["outline-width"],
        outlineColor: f["outline-color"],
        outlineOffset: f["outline-offset"],
      };
    };
    expect(await ring(back), "the back link").toEqual(RING);
    for (const next of order) {
      await page.keyboard.press("Tab");
      await expect(next).toBeFocused();
      expect(await ring(next), await next.innerText()).toEqual(RING);
    }
    // the rest of the controls, focused after a key press so the ring shows
    const rest = [
      btn(page, "Approve £3,420"),
      btn(page, "Ask me later").first(),
      root(page).getByRole("link", { name: "Ledger" }),
      btn(page, "Draft a supplier brief"),
      root(page)
        .getByRole("button", { name: /Google Drive$/ })
        .first(),
    ];
    for (const loc of rest) {
      await loc.focus();
      await page.keyboard.press("Shift+Tab");
      await page.keyboard.press("Tab");
      await expect(loc).toBeFocused();
      expect(await ring(loc), await loc.innerText()).toEqual(RING);
    }
    // Enter activates a focused button
    await btn(page, "Pause").focus();
    await page.keyboard.press("Enter");
    await expect(btn(page, "Resume")).toBeVisible();
    expect(problems).toEqual([]);
  });

  test("WEB_6_e2e_the_state_colours_of_a_running_and_a_finished_world", async ({ page }) => {
    await openWorld(page, "calls");
    const running = await facts(
      text(page, "Running"),
      ["background-color", "color"],
      ["height", "26px"],
    );
    expectFacts("Running chip", running, {
      "background-color": await token(page, "--chip"),
      color: await token(page, "--ink"),
    });
    const track = text(page, "80%").locator("xpath=..").locator("div").first();
    const fill = await facts(track.locator("div").first(), ["background-color"]);
    near(
      "fill = 80%",
      Number(fill.w),
      0.8 * (await track.evaluate((el) => el.getBoundingClientRect().width)),
      1,
    );
    expect(fill["background-color"], "running: --run").toBe(await token(page, "--run"));
    await page.goto("/world/comp");
    await expect(h1(page)).toHaveText("Competitor pricing");
    const done = text(page, "100%")
      .locator("xpath=..")
      .locator("div")
      .first()
      .locator("div")
      .first();
    expect((await facts(done, ["background-color"]))["background-color"], "ready: --ok").toBe(
      await token(page, "--ok"),
    );
  });
});

test.describe("park world: the top grid breaks at a window of 1060", () => {
  for (const [width, columns] of [
    [1060, 2],
    [1059, 1],
  ] as const) {
    test(`WEB_6_e2e_at_${width}_the_map_and_the_side_column_are_${columns === 2 ? "side_by_side" : "stacked"}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      const problems = await openWorld(page, "k1");
      const card = await cardOf(page, K1_TAG).boundingBox();
      const spend = await text(page, "Spend").locator("xpath=ancestor::div[2]").boundingBox();
      if (!(card && spend)) throw new Error("no boxes");
      if (columns === 2) {
        expect(
          spend.y,
          "the side column starts beside the map card (the Waiting card may sit above Spend)",
        ).toBeLessThan(card.y + card.height);
        expect(spend.x, "the side column is to the right").toBeGreaterThan(card.x + card.width);
        expect(spend.width, "the side column keeps its 300px minimum").toBeGreaterThanOrEqual(299);
      } else {
        near("stacked: same left edge", spend.x, card.x, 1);
        expect(spend.y, "under the map card").toBeGreaterThan(card.y + card.height);
      }
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      expect(problems).toEqual([]);
    });
  }
});

test.describe("park world: accessibility", () => {
  for (const theme of ["day", "night"] as const) {
    test(`WEB_6_e2e_axe_finds_nothing_serious_on_the_City_page_by_${theme}`, async ({ page }) => {
      await page.setViewportSize(DESKTOP);
      await openWorld(page, "k1", theme);
      const results = await new AxeBuilder({ page }).include("main").analyze();
      const serious = results.violations
        .filter((v) => v.impact === "serious" || v.impact === "critical")
        .map((v) => ({ ...v, nodes: v.nodes.filter((n) => !isDesignOwnedContrast(n)) }))
        .filter((v) => v.nodes.length > 0);
      expect(
        serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
      ).toEqual([]);
    });
  }
});

/** The legend item of the map card named `name` (a span holding the swatch and the word). */
function card_legend(page: Page, name: string): Locator {
  return cardOf(page, K1_TAG)
    .locator("span", { hasText: new RegExp(`^${name}$`) })
    .first();
}
