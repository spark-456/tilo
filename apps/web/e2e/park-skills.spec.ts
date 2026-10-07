// WEB-8a acceptance (plan sections 8a and 10; README "Skills" items 1 and 2): /skills in a real browser at
// 1440x900 and 390x844, day and night. The page runs alone inside ParkApp here (the shell, WEB-3b, adds the nav
// and the city). Every expected value was measured as a computed value on the reference page, served from
// design_handoff_tilo_web_app/design (`python -m http.server <port>`, open `Tilo App Skills` via
// `Tilo App.dc.html#skills`) at the same viewports, walking the whole flow (record, Tilo's version, run, save):
//   - header: the sheet (padding 28 32 40, gap 30, r28), h1 Nunito 900 36 / -0.8 / 37.8, "8 skills" 15/700, the
//     three pills (h30, 0 12, r999, 13.5/800), "Teach a skill" (h42, 0 18 0 14, r12, 15/800);
//   - the Teach card (r24, 1px line2), its head (20 24 18, gap 18, 64px tile r20), the step bar (4 equal tracks,
//     gap 10, 5px segments, 20px dots, locked steps at .5);
//   - step 1: method tiles (13 14, 2px border, r16), mock browser (min 290, r20, toast colours), capture button
//     (h40, #5A3FE0), "What Tilo has picked up" (16 18, gap 10, r20), captured rows (11 13, r14), name field (46 high
//     with its border), next button (h46, r13);
//   - step 2: bubble, plan rows (28 col, 11 13, r16), Ask me first switches (40x24 track, 18 knob, +16), the question
//     card (14 16, r18), answer pills (h36), estimates (10 13, r14), Back and Let Tilo try it (h44);
//   - step 3: art panel (min 300, r22), run rows (11 13, r16) and their states, Yes add it (h36, #F0A500), result;
//   - step 4: field, pickers (track 3 / r12, items h36 r9), the "starts as" card, the saved banner (18 22, r22).
// Motion is not built (BQ-WEB-3), so values that the reference reaches through a transition are checked at their
// end state. Night: the shell flips `data-time` on the data-park root; here the attribute is set on the page,
// which is all the CSS reads (colours are tokens).
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-skills.spec.ts --project=chromium --no-deps --workers=3
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";
import { DESKTOP, MOBILE } from "./support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;
type Theme = "day" | "night";

// ---- reference values (computed) ---------------------------------------------------------------------
const TOK = {
  day: {
    ink: "rgb(31, 29, 43)",
    ink2: "rgb(74, 70, 85)",
    ink3: "rgb(107, 103, 121)",
    hero: "rgb(90, 63, 224)",
    heroInk: "rgb(74, 49, 204)",
    heroSoft: "rgba(90, 63, 224, 0.1)",
    card: "rgb(255, 255, 255)",
    line: "rgba(31, 29, 43, 0.12)",
    line2: "rgba(31, 29, 43, 0.07)",
    sunk: "rgba(31, 29, 43, 0.043)",
    track: "rgba(31, 29, 43, 0.1)",
    okSoft: "rgba(31, 127, 68, 0.12)",
    okInk: "rgb(21, 94, 50)",
    ok: "rgb(30, 138, 76)",
    amberSoft: "rgb(255, 244, 218)",
    amberLine: "rgb(241, 212, 140)",
    amberTile: "rgb(255, 231, 176)",
    amberInk: "rgb(122, 80, 0)",
    toast: "rgb(31, 29, 43)",
    toastInk: "rgb(255, 255, 255)",
    seg: "rgba(31, 29, 43, 0.06)",
    tabOn: "rgb(255, 255, 255)",
    field: "rgb(255, 255, 255)",
    btn2: "rgb(255, 255, 255)",
    red: "rgb(200, 55, 45)",
    sheet: "rgba(250, 249, 246, 0.95)",
    gBd: "rgba(255, 255, 255, 0.85)",
    sh: "rgba(31, 29, 43, 0.06) 0px 1px 2px 0px, rgba(31, 29, 43, 0.45) 0px 18px 40px -24px",
  },
  night: {
    ink: "rgb(244, 242, 250)",
    ink2: "rgb(210, 206, 227)",
    ink3: "rgb(169, 165, 190)",
    hero: "rgb(122, 98, 245)",
    heroInk: "rgb(188, 175, 255)",
    heroSoft: "rgba(122, 98, 245, 0.22)",
    card: "rgba(255, 255, 255, 0.055)",
    line: "rgba(255, 255, 255, 0.13)",
    line2: "rgba(255, 255, 255, 0.07)",
    sunk: "rgba(255, 255, 255, 0.05)",
    track: "rgba(255, 255, 255, 0.14)",
    okSoft: "rgba(92, 203, 134, 0.16)",
    okInk: "rgb(134, 217, 162)",
    ok: "rgb(92, 203, 134)",
    amberSoft: "rgba(58, 42, 16, 0.85)",
    amberLine: "rgba(247, 200, 92, 0.45)",
    amberTile: "rgb(74, 56, 16)",
    amberInk: "rgb(247, 200, 92)",
    toast: "rgb(244, 242, 250)",
    toastInk: "rgb(31, 29, 43)",
    seg: "rgba(255, 255, 255, 0.08)",
    tabOn: "rgba(255, 255, 255, 0.16)",
    field: "rgba(255, 255, 255, 0.07)",
    btn2: "rgba(255, 255, 255, 0.1)",
    red: "rgb(255, 122, 110)",
    sheet: "rgba(22, 24, 54, 0.95)",
    gBd: "rgba(255, 255, 255, 0.14)",
    sh: "rgba(0, 0, 0, 0.3) 0px 1px 2px 0px, rgba(0, 0, 0, 0.75) 0px 18px 40px -24px",
  },
} as const;
const WHITE = "rgb(255, 255, 255)";
const AMBER = "rgb(240, 165, 0)"; // #F0A500, hard-coded by the design
const NEEDS_INK = "rgb(31, 29, 43)"; // #1F1D2B on the amber
const HERO_FIXED = "rgb(90, 63, 224)"; // #5A3FE0 on the capture button, both themes
const CAPTURED_GREEN = "rgb(30, 138, 76)"; // #1E8A4C on "Record again", both themes
const RING = {
  outlineStyle: "solid",
  outlineWidth: "3px",
  outlineColor: "rgb(90, 63, 224)",
  outlineOffset: "2px",
};

// Design-owned contrast exceptions (plan 8c: the design's own values win and the PR lists them). Matched by colour
// pair, never by selector. (1) white on the night hero fill #7A62F5 is 4.29:1 (every filled button by night);
// (2) the waiting dot of the practice run is white on #F0A500 (the reference's `dotFg` picks white for any current
// step, including the one that asks); (3) "Record again" is white on #1E8A4C (4.38:1; both hard-coded in the
// reference's `capBg` / `dotFg`). Anything else that axe reports is a failure.
const DESIGN_OWNED_CONTRAST = [
  ["#ffffff", "#7a62f5"],
  ["#ffffff", "#f0a500"],
  ["#ffffff", "#1e8a4c"],
] as const;
function isDesignOwnedContrast(node: { any: { data?: unknown }[] }): boolean {
  return node.any.some((check) => {
    const d = check.data as { fgColor?: string; bgColor?: string } | undefined;
    return DESIGN_OWNED_CONTRAST.some(([fg, bg]) => d?.fgColor === fg && d?.bgColor === bg);
  });
}

// ---- finding elements the way a reader would, then reading what the browser computed -------------------
interface Finder {
  /** Search inside the Teach card (default) or the whole page. */
  scope?: "card" | "page";
  css?: string;
  /** Whole text of the (deepest) element. */
  text?: string;
  includes?: string;
  startsWith?: string;
  w?: number;
  h?: number;
  padding?: string;
  minHeight?: string;
  /** A css selector, resolved inside the scope, whose subtree is searched. */
  within?: string;
}
type Facts = Record<string, string | number>;

async function facts(page: Page, f: Finder, props: readonly string[] = []): Promise<Facts> {
  const got = await page.evaluate(
    ({ f, props }) => {
      const scopeEl = document.querySelector(
        f.scope === "page"
          ? '[data-testid="park-page-skills"]'
          : 'section[aria-label="Teach a skill"]',
      );
      if (!scopeEl) return { error: "no scope" };
      const base = f.within ? scopeEl.querySelector(f.within) : scopeEl;
      if (!base) return { error: `no ${f.within}` };
      const all = [base, ...base.querySelectorAll(f.css ?? "*")].filter(
        (e) => !f.css || e.matches(f.css),
      );
      const hit = all.filter((e) => {
        const t = (e.textContent ?? "").trim();
        const r = e.getBoundingClientRect();
        const s = getComputedStyle(e);
        if (f.text !== undefined && t !== f.text) return false;
        if (f.includes !== undefined && !t.includes(f.includes)) return false;
        if (f.startsWith !== undefined && !t.startsWith(f.startsWith)) return false;
        if (f.w !== undefined && Math.abs(r.width - f.w) > 0.6) return false;
        if (f.h !== undefined && Math.abs(r.height - f.h) > 0.6) return false;
        if (f.padding !== undefined && s.getPropertyValue("padding") !== f.padding) return false;
        if (f.minHeight !== undefined && s.getPropertyValue("min-height") !== f.minHeight)
          return false;
        return true;
      });
      // the deepest match: the one with no other match inside it (for text), else the first
      const el = hit.find((e) => !hit.some((o) => o !== e && e.contains(o))) ?? hit[0];
      if (!el) return { error: `no element for ${JSON.stringify(f)}` };
      const s = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      const out: Record<string, string | number> = { x: r.x, y: r.y, w: r.width, h: r.height };
      for (const p of props) out[p] = s.getPropertyValue(p);
      return out;
    },
    { f, props },
  );
  if ("error" in got) throw new Error(String(got.error));
  return got as Facts;
}

const near = (label: string, got: unknown, want: number, tol = 0.6) =>
  expect(Math.abs(Number(got) - want), `${label}: ${got} vs ${want}`).toBeLessThanOrEqual(tol);

/** One probe: the computed values (and boxes, as `w` / `h`) the reference has for the element. */
async function expectEl(
  page: Page,
  label: string,
  f: Finder,
  want: Record<string, string | number>,
) {
  const props = Object.keys(want).filter((k) => k !== "w" && k !== "h");
  const got = await facts(page, f, props);
  for (const [k, v] of Object.entries(want)) {
    if (k === "w" || k === "h") near(`${label} ${k}`, got[k], Number(v));
    else expect(got[k], `${label} ${k}`).toBe(v);
  }
}

// ---- driving the page ------------------------------------------------------------------------------------
async function open(page: Page, theme: Theme): Promise<string[]> {
  const problems = collectConsoleProblems(page);
  await page.goto("/skills");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Skills");
  await expect(page.getByRole("button", { name: "Teach a skill", exact: true })).toBeVisible();
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  if (theme === "night") {
    await page.locator("[data-park]").evaluate((el) => el.setAttribute("data-time", "night"));
  }
  return problems;
}
const card = (page: Page) => page.getByRole("region", { name: "Teach a skill" });
const btn = (page: Page, name: string) => card(page).getByRole("button", { name, exact: true });
const steps = (page: Page) => card(page).getByRole("list", { name: "Steps" }).getByRole("button");

async function axe(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => ({
      id: v.id,
      nodes: v.nodes.filter((n) => !(v.id === "color-contrast" && isDesignOwnedContrast(n))),
    }))
    .filter((v) => v.nodes.length > 0)
    .map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) }));
}

// A cold Vite dev server optimises its dependencies on the first request and reloads the page; warm it
// once per worker so no test pays for it.
test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(150_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/skills", { timeout: 120_000 });
  await page
    .getByRole("heading", { level: 1 })
    .waitFor({ timeout: 120_000 })
    .catch(() => undefined);
  await page.close();
});

for (const [sizeName, viewport] of Object.entries(SIZES)) {
  for (const theme of ["day", "night"] as const) {
    const T = TOK[theme];
    test.describe(`park skills at ${sizeName}, ${theme}`, () => {
      test.use({ viewport });

      test(`WEB_8a_e2e_${sizeName}_${theme}_the_header_and_step_1_match_the_reference`, async ({
        page,
      }) => {
        const problems = await open(page, theme);
        const P = (label: string, f: Finder, want: Record<string, string | number>) =>
          expectEl(page, label, { scope: "page", ...f }, want);
        const C = (label: string, f: Finder, want: Record<string, string | number>) =>
          expectEl(page, label, f, want);

        // the sheet, the title row and the pills
        await P(
          "sheet",
          { css: ".park-sheet" },
          {
            padding: "28px 32px 40px",
            "row-gap": "30px",
            "border-radius": "28px",
            "border-top-width": "1px",
            "background-color": T.sheet,
            "box-shadow": T.sh,
            color: T.ink,
            "border-top-color": T.gBd,
          },
        );
        await P(
          "h1",
          { css: "h1" },
          {
            "font-family": "Nunito, sans-serif",
            "font-size": "36px",
            "font-weight": "900",
            "letter-spacing": "-0.8px",
            "line-height": "37.8px",
            color: T.ink,
          },
        );
        await P(
          "total",
          { text: "8 skills" },
          { "font-size": "15px", "font-weight": "700", color: T.ink3 },
        );
        await P(
          "intro",
          { css: "p", startsWith: "Teach your agents new work" },
          {
            "font-size": "15.5px",
            "font-weight": "600",
            color: T.ink2,
          },
        );
        const pill = {
          padding: "0px 12px",
          "border-radius": "999px",
          "font-size": "13.5px",
          "font-weight": "800",
          h: 30,
        };
        await P(
          "pill trusted",
          { text: "4 trusted" },
          {
            ...pill,
            "background-color":
              theme === "day" ? "rgba(31, 127, 68, 0.12)" : "rgba(92, 203, 134, 0.16)",
            color: T.okInk,
          },
        );
        await P(
          "pill learning",
          { text: "2 learning" },
          { ...pill, "background-color": T.heroSoft, color: T.heroInk },
        );
        await P(
          "pill need your help",
          { text: "6 need your help" },
          { ...pill, "background-color": T.amberTile, color: T.amberInk },
        );
        await P(
          "Teach a skill",
          { css: "button", text: "Teach a skill" },
          {
            h: 42,
            padding: "0px 18px 0px 14px",
            gap: "8px",
            "border-radius": "12px",
            "background-color": T.hero,
            color: WHITE,
            "font-size": "15px",
            "font-weight": "800",
          },
        );

        // the card and its head
        await P(
          "card",
          { css: 'section[aria-label="Teach a skill"]' },
          {
            "border-radius": "24px",
            "border-top-width": "1px",
            "border-top-color": T.line2,
            "background-color": T.card,
            overflow: "hidden",
            color: T.ink,
          },
        );
        await C(
          "card head",
          { padding: "20px 24px 18px" },
          { gap: "18px", "border-bottom-width": "1px", "border-bottom-color": T.line2 },
        );
        await C(
          "teacher tile",
          { w: 64, h: 64 },
          { "border-radius": "20px", "background-color": T.heroSoft },
        );
        await C(
          "card title",
          { css: "h2", text: "Teach Tilo something new" },
          {
            "font-family": "Nunito, sans-serif",
            "font-size": "24px",
            "font-weight": "900",
            "letter-spacing": "-0.4px",
            "line-height": "27.6px",
            color: T.ink,
          },
        );
        await C(
          "card line",
          { startsWith: "Show it once. Tilo repeats it" },
          {
            "font-size": "14.5px",
            "font-weight": "600",
            color: T.ink2,
            "margin-top": "4px",
            "line-height": "21.025px",
          },
        );

        // the step bar: four equal tracks, locked steps at .5, the current one in hero
        const bar = await facts(page, { css: 'ol[aria-label="Steps"]' }, [
          "display",
          "column-gap",
          "grid-template-columns",
        ]);
        expect(bar.display).toBe("grid");
        expect(bar["column-gap"]).toBe("10px");
        const tracks = String(bar["grid-template-columns"]).split(" ");
        expect(tracks, "four tracks").toHaveLength(4);
        expect(new Set(tracks.map((t) => Math.round(Number.parseFloat(t)))).size).toBe(1);
        await expect(steps(page)).toHaveCount(4);
        await expect(steps(page).nth(0)).toHaveAttribute("aria-current", "step");
        await expect(steps(page).nth(1)).toBeDisabled();
        const s1 = 'ol[aria-label="Steps"] li:nth-child(1) button';
        const s2 = 'ol[aria-label="Steps"] li:nth-child(2) button';
        await C(
          "step 1 segment",
          { within: s1, h: 5 },
          { "border-radius": "99px", "background-color": T.hero },
        );
        await C(
          "step 1 dot",
          { within: s1, w: 20, h: 20 },
          {
            "border-radius": "99px",
            "background-color": T.hero,
            color: WHITE,
            "font-size": "11.5px",
            "font-weight": "800",
          },
        );
        await C("step 2 button", { css: s2 }, { opacity: "0.5" });
        await C(
          "step 2 segment",
          { within: s2, h: 5 },
          { "border-radius": "99px", "background-color": T.track },
        );
        await C(
          "step 2 dot",
          { within: s2, w: 20, h: 20 },
          { "background-color": T.track, color: T.ink2 },
        );

        // step 1: method tiles
        const tile = (name: string) => ({ css: "button", startsWith: name });
        await C("method tile (chosen)", tile("Record my screen"), {
          padding: "13px 14px",
          gap: "12px",
          "border-top-width": "2px",
          "border-radius": "16px",
          "border-top-color": T.hero,
          "background-color": T.heroSoft,
          color: T.ink,
        });
        await C("method tile (idle)", tile("Guided walkthrough"), {
          "border-top-color": T.line,
          "background-color": T.card,
          "border-radius": "16px",
        });
        await C(
          "method icon (chosen)",
          { within: 'button[aria-pressed="true"]', w: 36, h: 36 },
          { "border-radius": "11px", "background-color": T.card, color: T.heroInk },
        );
        await C(
          "method name",
          { text: "Record my screen" },
          { "font-size": "14.5px", "font-weight": "800", color: T.ink },
        );
        await C(
          "method line",
          { text: "Do it once while Tilo watches" },
          { "font-size": "13px", "font-weight": "600", color: T.ink2 },
        );
        const tiles = await Promise.all(
          ["Record my screen", "Guided walkthrough", "Describe it", "Upload an example"].map((n) =>
            facts(page, tile(n)),
          ),
        );
        if (sizeName === "desktop") {
          expect(
            new Set(tiles.map((t) => Math.round(Number(t.y)))).size,
            "four tiles in one row",
          ).toBe(1);
        } else {
          expect(
            new Set(tiles.map((t) => Math.round(Number(t.x)))).size,
            "tiles stacked in one column",
          ).toBe(1);
          expect(new Set(tiles.map((t) => Math.round(Number(t.y)))).size).toBe(4);
        }

        // the mock browser, the capture button and the picked-up panel
        await C(
          "mock browser",
          { minHeight: "290px" },
          {
            "border-radius": "20px",
            "background-color": T.toast,
            color: T.toastInk,
            overflow: "hidden",
          },
        );
        await C(
          "mock address",
          { text: "mail.northwind.co/accounts" },
          {
            h: 24,
            "border-radius": "8px",
            "background-color": "rgba(127, 127, 140, 0.2)",
            "font-size": "12.5px",
            "font-weight": "700",
            opacity: "0.85",
          },
        );
        await C(
          "mock hint",
          { text: "Do the task as normal. Tilo notes each step." },
          { "font-size": "13.5px", "font-weight": "700", opacity: "0.8" },
        );
        await C(
          "capture button",
          { css: "button", text: "Start recording" },
          {
            h: 40,
            padding: "0px 16px",
            gap: "8px",
            "border-radius": "12px",
            "background-color": HERO_FIXED,
            color: WHITE,
            "font-size": "14.5px",
            "font-weight": "800",
          },
        );
        await C(
          "picked-up panel",
          { padding: "16px 18px", includes: "What Tilo has picked up" },
          { gap: "10px", "border-radius": "20px", "background-color": T.sunk },
        );
        await C(
          "picked-up title",
          { text: "What Tilo has picked up" },
          { "font-size": "15px", "font-weight": "800", color: T.ink },
        );
        await C(
          "picked-up count",
          { text: "0 of 4" },
          { "font-size": "13px", "font-weight": "800", color: T.ink2 },
        );
        await C(
          "nothing yet",
          { text: "Steps appear here as Tilo watches." },
          { padding: "16px", gap: "6px", "font-size": "14px", "font-weight": "600", color: T.ink2 },
        );
        await C(
          "skill name",
          { css: "input" },
          {
            h: 46,
            padding: "0px 14px",
            "border-top-width": "1px",
            "border-top-color": T.line,
            "border-radius": "12px",
            "background-color": T.field,
            "font-size": "15px",
            "font-weight": "700",
            color: T.ink,
          },
        );
        await C(
          "next button (locked)",
          { css: "button", text: "Show me Tilo’s version" },
          {
            h: 46,
            "border-radius": "13px",
            "background-color": T.track,
            color: T.ink2,
            "font-size": "15px",
            "font-weight": "800",
          },
        );
        if (sizeName === "desktop") {
          const a = await facts(page, { css: "div", minHeight: "290px" });
          const b = await facts(page, {
            padding: "16px 18px",
            includes: "What Tilo has picked up",
          });
          near("the two columns sit side by side", a.y, Number(b.y), 1);
        }

        // describe and upload variants
        await card(page)
          .getByRole("button", { name: /^Describe it/ })
          .click();
        await C(
          "task field",
          { css: "textarea" },
          {
            "min-height": "210px",
            padding: "16px 18px",
            "border-top-width": "1px",
            "border-top-color": T.line,
            "border-radius": "18px",
            "background-color": T.field,
            "font-size": "15px",
            "font-weight": "600",
            "line-height": "23.25px",
            color: T.ink,
          },
        );
        await C(
          "read button",
          { css: "button", text: "Read my description" },
          {
            h: 40,
            padding: "0px 16px",
            "border-radius": "12px",
            "background-color": T.hero,
            color: WHITE,
            "font-size": "14.5px",
            "font-weight": "800",
          },
        );
        await card(page)
          .getByRole("button", { name: /^Upload an example/ })
          .click();
        await C(
          "dropzone",
          { css: "button", startsWith: "Drop an example here" },
          {
            "min-height": "290px",
            padding: "24px",
            gap: "10px",
            "border-top-width": "2px",
            "border-top-style": "dashed",
            "border-top-color": T.line,
            "border-radius": "20px",
            "background-color": T.sunk,
            color: T.ink,
          },
        );
        await C(
          "drop icon",
          { w: 52, h: 52 },
          { "border-radius": "16px", "background-color": T.card, color: T.heroInk },
        );
        await C(
          "drop title",
          { text: "Drop an example here" },
          { "font-size": "17px", "font-weight": "800", color: T.ink },
        );
        await C(
          "drop line",
          { startsWith: "A finished spreadsheet" },
          { "font-size": "13.5px", "font-weight": "600", color: T.ink2, "line-height": "19.575px" },
        );
        expect(problems).toEqual([]);
      });

      test(`WEB_8a_e2e_${sizeName}_${theme}_the_whole_flow_in_real_time_matches_the_reference`, async ({
        page,
      }) => {
        test.setTimeout(120_000);
        const problems = await open(page, theme);
        const C = (label: string, f: Finder, want: Record<string, string | number>) =>
          expectEl(page, label, f, want);
        const scrollOverflow = () =>
          page.evaluate(
            () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
          );

        // Record my screen: a step every 900 ms, REC label and one watched row while it records
        await btn(page, "Start recording").click();
        await expect(card(page).getByText("REC 00:02", { exact: true })).toBeVisible();
        await C(
          "recording button",
          { css: "button", text: "Recording…" },
          { "background-color": T.red, color: WHITE, h: 40 },
        );
        const watched = () =>
          page.evaluate(
            () =>
              [...document.querySelectorAll('section[aria-label="Teach a skill"] *')].filter(
                (e) => getComputedStyle(e).boxShadow === "rgb(240, 165, 0) 0px 0px 0px 3px",
              ).length,
          );
        expect(await watched(), "one mock row ringed while recording").toBe(1);
        const started = Date.now();
        await expect(card(page).getByText("0 of 4", { exact: true })).toBeVisible();
        await expect(card(page).getByText("1 of 4", { exact: true })).toBeVisible({
          timeout: 3000,
        });
        expect(Date.now() - started, "the first step arrives about 900 ms in").toBeGreaterThan(500);
        await expect(card(page).getByText("4 of 4", { exact: true })).toBeVisible({
          timeout: 8000,
        });
        expect(Date.now() - started, "four steps take about 3.6 s").toBeGreaterThan(2500);
        expect(Date.now() - started).toBeLessThan(8000);
        expect(await watched(), "no ring once it has the four").toBe(0);
        await C(
          "Record again",
          { css: "button", text: "Record again" },
          { "background-color": CAPTURED_GREEN, color: WHITE, h: 40 },
        );
        await C(
          "captured row",
          { padding: "11px 13px", includes: "Opened the new email from Northline" },
          {
            gap: "12px",
            "border-radius": "14px",
            "background-color": TOK[theme].card,
            display: "grid",
          },
        );
        await C(
          "captured number",
          { w: 26, h: 26, text: "1" },
          {
            "border-radius": "9px",
            "background-color": TOK[theme].heroSoft,
            color: TOK[theme].heroInk,
            "font-size": "12.5px",
            "font-weight": "800",
          },
        );
        await C(
          "captured text",
          { text: "Opened the new email from Northline in the Accounts inbox" },
          {
            "font-size": "14px",
            "font-weight": "700",
            "line-height": "19.6px",
            "padding-top": "3px",
            color: TOK[theme].ink,
          },
        );
        await C(
          "captured hint",
          { text: "Got it. 4 steps captured." },
          {
            "font-size": "13.5px",
            "font-weight": "700",
            opacity: "0.8",
            color: TOK[theme].toastInk,
          },
        );
        await C(
          "next button (ready)",
          { css: "button", text: "Show me Tilo’s version" },
          { h: 46, "background-color": TOK[theme].hero, color: WHITE },
        );
        expect(await axe(page), "axe, step 1").toEqual([]);
        expect(await scrollOverflow()).toBeLessThanOrEqual(0);

        // Tilo's version
        await btn(page, "Show me Tilo’s version").click();
        await expect(steps(page).nth(1)).toHaveAttribute("aria-current", "step");
        const s1 = 'ol[aria-label="Steps"] li:nth-child(1) button';
        await C("step 1 is done (green)", { within: s1, h: 5 }, { "background-color": T.ok });
        await C(
          "step 1 dot is done",
          { within: s1, w: 20, h: 20 },
          { "background-color": T.ok, color: WHITE },
        );
        await C(
          "bubble tile",
          { w: 44, h: 44 },
          { "border-radius": "14px", "background-color": T.heroSoft },
        );
        await C(
          "bubble",
          { startsWith: "Here’s how I’d do Log new supplier invoices" },
          {
            padding: "11px 15px",
            "border-radius": "4px 18px 18px",
            "background-color": T.heroSoft,
            "font-size": "14.5px",
            "font-weight": "600",
            "line-height": "21.025px",
          },
        );
        const row1 = "Check the Accounts inbox for new supplier invoices";
        await C(
          "plan row",
          { padding: "11px 13px", includes: row1 },
          {
            gap: "12px",
            "border-top-width": "1px",
            "border-top-color": T.line,
            "border-radius": "16px",
            display: "grid",
          },
        );
        const cols = String(
          (await facts(page, { padding: "11px 13px", includes: row1 }, ["grid-template-columns"]))[
            "grid-template-columns"
          ],
        ).split(" ");
        expect(cols[0]).toBe("28px");
        expect(cols, "number, text, switch").toHaveLength(3);
        await C(
          "plan number",
          { w: 28, h: 28, text: "1" },
          {
            "border-radius": "9px",
            "background-color": T.sunk,
            "font-size": "12.5px",
            "font-weight": "800",
          },
        );
        await C(
          "plan text",
          { text: row1 },
          { "font-size": "14.5px", "font-weight": "800", "line-height": "19.575px", color: T.ink },
        );
        await C(
          "plan tool",
          { text: "Gmail · Read" },
          {
            "font-size": "12.5px",
            "font-weight": "700",
            color: T.ink2,
            "margin-top": "3px",
            gap: "6px",
          },
        );
        await C(
          "switch (on)",
          { css: '[role="switch"][aria-checked="true"]' },
          { "font-size": "12.5px", "font-weight": "800", color: T.amberInk, gap: "8px" },
        );
        await C(
          "track (on)",
          { within: '[role="switch"][aria-checked="true"]', w: 40, h: 24 },
          { "background-color": AMBER, "border-radius": "999px", padding: "3px" },
        );
        await C(
          "knob (on)",
          { within: '[role="switch"][aria-checked="true"]', w: 18, h: 18 },
          {
            "background-color": WHITE,
            "border-radius": "999px",
            "box-shadow": "rgba(0, 0, 0, 0.2) 0px 1px 2px 0px",
            transform: "matrix(1, 0, 0, 1, 16, 0)",
          },
        );
        await C(
          "switch (off)",
          { css: '[role="switch"][aria-checked="false"]' },
          { color: T.ink2 },
        );
        await C(
          "track (off)",
          { within: '[role="switch"][aria-checked="false"]', w: 40, h: 24 },
          { "background-color": T.track },
        );
        await C(
          "knob (off)",
          { within: '[role="switch"][aria-checked="false"]', w: 18, h: 18 },
          { transform: "none", "background-color": WHITE },
        );
        await C(
          "question card",
          { padding: "14px 16px", includes: "ONE QUESTION" },
          {
            "background-color": T.amberSoft,
            "border-top-width": "1px",
            "border-top-color": T.amberLine,
            "border-radius": "18px",
            gap: "12px",
          },
        );
        await C(
          "question tile",
          { w: 42, h: 42 },
          { "border-radius": "13px", "background-color": T.card },
        );
        await C(
          "question eyebrow",
          { text: "ONE QUESTION" },
          {
            "font-size": "12px",
            "font-weight": "800",
            "letter-spacing": "0.5px",
            color: T.amberInk,
          },
        );
        await C(
          "question text",
          { text: "Some invoices arrive as a link, not a PDF. What should I do?" },
          { "font-size": "15px", "font-weight": "800", color: T.ink },
        );
        await C(
          "answer pill",
          { css: "button", text: "Open the link" },
          {
            h: 36,
            padding: "0px 13px",
            "border-radius": "999px",
            "border-top-width": "1px",
            "border-top-color": T.line,
            "background-color": T.card,
            color: T.ink,
            "font-size": "13.5px",
            "font-weight": "800",
          },
        );
        await btn(page, "Open the link").click();
        await C(
          "answer pill (chosen)",
          { css: "button", text: "Open the link" },
          { "background-color": T.toast, color: T.toastInk },
        );
        await C(
          "estimate tile",
          { padding: "10px 13px", includes: "Each run" },
          { "background-color": T.sunk, "border-radius": "14px" },
        );
        await C(
          "estimate label",
          { text: "Each run" },
          { "font-size": "12px", "font-weight": "700", color: T.ink3 },
        );
        await C(
          "estimate value",
          { text: "~£0.40" },
          { "font-size": "18px", "font-weight": "800", color: T.ink },
        );
        await C(
          "learn note",
          { startsWith: "Tilo tries this once" },
          { "font-size": "13.5px", "font-weight": "600", color: T.ink2, "line-height": "20.25px" },
        );
        await C(
          "Back",
          { css: "button", text: "Back" },
          {
            h: 44,
            padding: "0px 18px",
            "border-top-width": "1px",
            "border-top-color": T.line,
            "border-radius": "12px",
            "background-color": T.btn2,
            "font-size": "14.5px",
            "font-weight": "800",
            color: T.ink,
          },
        );
        await C(
          "Let Tilo try it",
          { css: "button", text: "Let Tilo try it" },
          {
            h: 44,
            "border-radius": "12px",
            "background-color": T.hero,
            color: WHITE,
            "font-size": "15px",
            "font-weight": "800",
          },
        );
        expect(await axe(page), "axe, step 2").toEqual([]);
        expect(await scrollOverflow()).toBeLessThanOrEqual(0);

        // Try run: working, then it stops and asks, then it finishes
        await btn(page, "Let Tilo try it").click();
        await C(
          "art panel",
          { minHeight: "300px" },
          {
            "border-radius": "22px",
            "background-color": T.heroSoft,
            padding: "0px 20px 30px",
            gap: "4px",
            overflow: "hidden",
          },
        );
        await C(
          "practice pill",
          { text: "Practice run · Northline invoice #2291" },
          {
            h: 30,
            padding: "0px 12px",
            "border-radius": "999px",
            "background-color": T.card,
            "font-size": "13px",
            "font-weight": "800",
          },
        );
        await C(
          "status pill",
          { text: "Step 1 of 4" },
          {
            h: 30,
            "background-color": T.card,
            color: T.heroInk,
            "font-size": "13px",
            "font-weight": "800",
          },
        );
        await C(
          "run row (working)",
          { padding: "11px 13px", includes: row1 },
          {
            gap: "10px",
            "border-radius": "16px",
            "background-color": T.heroSoft,
            "border-top-color": "rgba(0, 0, 0, 0)",
            "border-top-width": "1px",
          },
        );
        await C(
          "run dot (working)",
          { w: 28, h: 28, text: "1" },
          {
            "border-radius": "99px",
            "background-color": T.hero,
            color: WHITE,
            "font-size": "12.5px",
            "font-weight": "800",
          },
        );
        await C(
          "run status (working)",
          { text: "Working…" },
          { "font-size": "12.5px", "font-weight": "800", color: T.heroInk },
        );
        await C(
          "run row (to come)",
          { padding: "11px 13px", includes: "Read supplier, invoice number" },
          { "border-top-color": T.line, "background-color": "rgba(0, 0, 0, 0)" },
        );
        await C(
          "run status (to come)",
          { text: "Waiting" },
          { color: T.ink3, "font-size": "12.5px", "font-weight": "800" },
        );
        await expect(btn(page, "Yes, add it")).toBeVisible({ timeout: 6000 });
        await C(
          "run row (asking)",
          { padding: "11px 13px", includes: "Add a row to “Invoices 2026”" },
          {
            "background-color": T.amberSoft,
            "border-top-color": T.amberLine,
            "border-top-width": "1px",
            "border-radius": "16px",
          },
        );
        await C("run dot (asking)", { w: 28, h: 28, text: "3" }, { "background-color": AMBER });
        await C(
          "run status (asking)",
          { text: "Asking you" },
          { color: T.amberInk, "font-size": "12.5px", "font-weight": "800" },
        );
        await C(
          "run pill (asking)",
          { text: "Waiting for you" },
          { "background-color": AMBER, color: NEEDS_INK },
        );
        await C(
          "ask prompt",
          { startsWith: "Add Northline Components" },
          { "font-size": "13.5px", "font-weight": "600", color: T.ink2 },
        );
        await C(
          "Yes, add it",
          { css: "button", text: "Yes, add it" },
          {
            h: 36,
            padding: "0px 14px",
            "border-radius": "11px",
            "background-color": AMBER,
            color: NEEDS_INK,
            "font-size": "14px",
            "font-weight": "800",
          },
        );
        expect(await axe(page), "axe, asking").toEqual([]);
        await btn(page, "Yes, add it").click();
        await expect(
          card(page).getByText("Matched your way of doing it", { exact: true }),
        ).toBeVisible({ timeout: 4000 });
        await C(
          "result",
          { padding: "13px 15px", includes: "Matched your way of doing it" },
          { "background-color": T.okSoft, "border-radius": "18px", gap: "12px" },
        );
        await C(
          "result title",
          { text: "Matched your way of doing it" },
          { "font-size": "15px", "font-weight": "800", color: T.okInk },
        );
        await C(
          "result line",
          { text: "4 of 4 steps · 1 min 08s · £0.38" },
          { "font-size": "13.5px", "font-weight": "600", color: T.okInk },
        );
        await C(
          "Fix a step",
          { css: "button", text: "Fix a step" },
          {
            h: 40,
            padding: "0px 14px",
            "border-radius": "12px",
            "background-color": T.btn2,
            "border-top-color": T.line,
            "font-size": "14px",
            "font-weight": "800",
          },
        );
        await C(
          "Looks right",
          { css: "button", text: "Looks right" },
          {
            h: 40,
            padding: "0px 16px",
            "border-radius": "12px",
            "background-color": T.hero,
            color: WHITE,
            "font-size": "14px",
            "font-weight": "800",
          },
        );
        await C(
          "run pill (finished)",
          { text: "Finished" },
          { "background-color": T.okSoft, color: T.okInk },
        );
        await C(
          "run status (done)",
          { text: "Done" },
          { color: T.okInk, "font-size": "12.5px", "font-weight": "800" },
        );
        await expect(steps(page).nth(3)).toBeEnabled();
        expect(await axe(page), "axe, finished").toEqual([]);

        // Save
        await btn(page, "Looks right").click();
        await expect(steps(page).nth(3)).toHaveAttribute("aria-current", "step");
        await C(
          "form label",
          { text: "Skill name" },
          { "font-size": "13px", "font-weight": "800", color: T.ink2 },
        );
        await C(
          "save field",
          { css: "input" },
          {
            h: 48,
            padding: "0px 14px",
            "border-top-width": "1px",
            "border-top-color": T.line,
            "border-radius": "12px",
            "background-color": T.field,
            "font-size": "16px",
            "font-weight": "800",
            color: T.ink,
          },
        );
        await C(
          "picker track",
          { padding: "3px", includes: "Just me" },
          { "background-color": T.seg, "border-radius": "12px", gap: "2px" },
        );
        await C(
          "picker item (chosen)",
          { css: "button", text: "Northwind Ops" },
          {
            h: 36,
            padding: "0px 14px",
            "border-radius": "9px",
            "background-color": T.tabOn,
            "box-shadow": "rgba(31, 29, 43, 0.16) 0px 1px 3px 0px",
            color: T.ink,
            "font-size": "14px",
            "font-weight": "800",
          },
        );
        await C(
          "picker item (idle)",
          { css: "button", text: "Just me" },
          { h: 36, "background-color": "rgba(0, 0, 0, 0)", "box-shadow": "none", color: T.ink2 },
        );
        await C(
          "trigger (chosen)",
          { css: "button", text: "When an invoice arrives" },
          { "background-color": T.tabOn, color: T.ink },
        );
        await C(
          "starts-as card",
          { padding: "14px 16px", includes: "It starts as Learning" },
          { "background-color": T.heroSoft, "border-radius": "18px", gap: "14px" },
        );
        await C(
          "starts-as tile",
          { w: 48, h: 48 },
          { "border-radius": "15px", "background-color": T.card },
        );
        await C(
          "starts-as text",
          { startsWith: "It starts as Learning" },
          { "font-size": "14px", "font-weight": "600", "line-height": "20.3px" },
        );
        await C(
          "Save skill",
          { css: "button", text: "Save skill" },
          {
            h: 44,
            "border-radius": "12px",
            "background-color": T.hero,
            color: WHITE,
            "font-size": "15px",
            "font-weight": "800",
          },
        );
        expect(await axe(page), "axe, save").toEqual([]);
        await btn(page, "Save skill").click();
        await C(
          "saved banner",
          { padding: "18px 22px", includes: "is now a skill" },
          { "background-color": T.okSoft, "border-radius": "22px", gap: "20px" },
        );
        await C(
          "saved tile",
          { w: 76, h: 76 },
          { "border-radius": "22px", "background-color": T.card },
        );
        await C(
          "saved title",
          { text: "“Log new supplier invoices” is now a skill" },
          {
            "font-family": "Nunito, sans-serif",
            "font-size": "22px",
            "font-weight": "900",
            "line-height": "30.8px",
            color: T.okInk,
          },
        );
        await C(
          "saved line",
          { text: "Shared with Northwind Ops · runs when an invoice arrives · starts as Learning" },
          { "font-size": "14.5px", "font-weight": "600", "line-height": "20.3px", color: T.okInk },
        );
        await C(
          "View in library",
          { css: "button", text: "View in library" },
          {
            h: 42,
            padding: "0px 16px",
            "border-radius": "12px",
            "background-color": T.hero,
            color: WHITE,
            "font-size": "14.5px",
            "font-weight": "800",
          },
        );
        await C(
          "Teach another",
          { css: "button", text: "Teach another" },
          {
            h: 42,
            padding: "0px 16px",
            "border-radius": "12px",
            "background-color": T.btn2,
            "border-top-color": T.line,
            "font-size": "14.5px",
            "font-weight": "800",
          },
        );
        for (let i = 0; i < 4; i++) await expect(steps(page).nth(i)).toBeDisabled();
        await expect(page.getByText("3 learning", { exact: true })).toBeVisible();
        expect(await axe(page), "axe, saved").toEqual([]);
        expect(await scrollOverflow()).toBeLessThanOrEqual(0);
        expect(problems).toEqual([]);
      });
    });
  }
}

test.describe("park skills: keyboard", () => {
  test.use({ viewport: DESKTOP });

  test("WEB_8a_e2e_keyboard_the_flow_can_be_driven_without_a_mouse_and_focus_is_visible", async ({
    page,
  }) => {
    const problems = await open(page, "day");
    // the first control of the PAGE is "Teach a skill" (the shell's nav comes first in the document, so start from
    // the page heading, where the shell puts focus after a navigation); focus shows the design's ring
    await page.getByRole("heading", { level: 1 }).evaluate((h) => {
      h.setAttribute("tabindex", "-1");
      (h as HTMLElement).focus();
    });
    await page.keyboard.press("Tab");
    const teach = page.getByRole("button", { name: "Teach a skill", exact: true });
    await expect(teach).toBeFocused();
    const ring = await teach.evaluate((el) => {
      const s = getComputedStyle(el);
      return {
        outlineStyle: s.outlineStyle,
        outlineWidth: s.outlineWidth,
        outlineColor: s.outlineColor,
        outlineOffset: s.outlineOffset,
      };
    });
    expect(ring).toEqual(RING);
    // Tab reaches the method tiles; Space chooses one; Enter starts what the focused button says
    const describe = card(page).getByRole("button", { name: /^Describe it/ });
    await describe.focus();
    await page.keyboard.press("Space");
    await expect(describe).toHaveAttribute("aria-pressed", "true");
    await card(page).getByRole("button", { name: "Read my description", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(card(page).getByText("4 of 4", { exact: true })).toBeVisible();
    await btn(page, "Show me Tilo’s version").focus();
    await page.keyboard.press("Enter");
    // the Ask me first switches are real switches: Space flips one
    const switches = card(page).getByRole("switch");
    await expect(switches).toHaveCount(4);
    await expect(switches.nth(2)).toBeChecked();
    await switches.nth(0).focus();
    await page.keyboard.press("Space");
    await expect(switches.nth(0)).toBeChecked();
    await expect(card(page).getByText("2 steps", { exact: true })).toBeVisible();
    // the step bar is reachable and an earlier step can be revisited from the keyboard
    await steps(page).nth(0).focus();
    await page.keyboard.press("Enter");
    await expect(steps(page).nth(0)).toHaveAttribute("aria-current", "step");
    await expect(card(page).getByText("4 of 4", { exact: true })).toBeVisible();
    expect(problems).toEqual([]);
  });

  test("WEB_8a_e2e_Teach_a_skill_scrolls_the_card_up_to_just_under_the_top_of_the_page", async ({
    page,
  }) => {
    // The reference scrolls to the card's top minus 96 (the nav's height); a short window leaves room to scroll.
    await open(page, "day");
    await page.setViewportSize({ width: 1440, height: 500 });
    const before = (await card(page).boundingBox())?.y ?? 0;
    await page.getByRole("button", { name: "Teach a skill", exact: true }).click();
    await expect
      .poll(async () => Math.round((await card(page).boundingBox())?.y ?? 9999), { timeout: 4000 })
      .toBeLessThan(before);
    await page.waitForTimeout(800); // a smooth scroll settles
    const y = (await card(page).boundingBox())?.y ?? 9999;
    expect(y).toBeGreaterThanOrEqual(56);
    expect(y).toBeLessThanOrEqual(130);
  });
});
