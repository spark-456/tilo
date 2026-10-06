// PRD 18.2 / 18.6 (issue #227 Bundle A): every text element on every routed screen uses a size on
// the 12/14/16/20/24/32/40 px scale, and the page title is one role: 40 px desktop, 32 px mobile.
// Not measured: ::before and ::after content, and text drawn on a canvas (the stage); neither is
// in the DOM text, so a size set there is outside this spec.
import { expect, test } from "@playwright/test";
import { SCREENS } from "../src/screens/meta";
import { DESKTOP, MOBILE } from "./support/viewports";

const SCALE = [12, 14, 16, 20, 24, 32, 40];
const FIXTURE = "/world/w_village_basic?fixture=village-basic&seq=44";

// Every routed screen (S-20 and S-25 are deferred and have no path), the dev indexes, the not-found
// page and the fixture-mode world, which has the stage labels and the Trace list.
const ROUTES = [
  ...SCREENS.filter((s) => s.path !== null).map((s) => ({ name: s.id, path: s.path as string })),
  { name: "fixture-world", path: FIXTURE },
  { name: "more", path: "/more" },
  { name: "screens-index", path: "/screens" },
  { name: "not-found", path: "/world/none/unknown" },
];

/** Selector and size of every element that draws text (an own text node, an SVG label, or a form
 * control) whose computed font size is off the scale. */
async function offScale(page: import("@playwright/test").Page) {
  return page.evaluate((scale) => {
    const bad: string[] = [];
    const name = (el: Element) => {
      const id = el.id ? `#${el.id}` : "";
      const cls =
        typeof el.className === "string" && el.className
          ? `.${el.className.trim().split(/\s+/).join(".")}`
          : "";
      return `${el.tagName.toLowerCase()}${id}${cls}`;
    };
    for (const el of document.body.querySelectorAll("*")) {
      if (["SCRIPT", "STYLE", "NOSCRIPT"].includes(el.tagName)) continue;
      const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent?.trim());
      const control = ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
      if (!own && !control) continue;
      const px = Number.parseFloat(getComputedStyle(el).fontSize);
      if (!scale.includes(px)) bad.push(`${name(el)} ${px}px`);
    }
    return bad;
  }, SCALE);
}

// The title size and the page shell's top offset: 32 px on both, since the dev banner has its own strip (#227 C2).
for (const [label, viewport, h1, top] of [
  ["desktop 1440x900", DESKTOP, 40, 32],
  ["mobile 390x844", MOBILE, 32, 32],
] as const) {
  test.describe(`PRD-18.2 type ramp at ${label}`, () => {
    test.use({ viewport });

    for (const route of ROUTES) {
      test(`PRD-18.2 ${route.name}: every text size is on the 12/14/16/20/24/32/40 scale`, async ({
        page,
      }) => {
        await page.goto(route.path);
        await page
          .locator("main, [data-testid='stage-frame'], [data-testid='screen-page']")
          .first()
          .waitFor();
        await page.waitForTimeout(500);
        expect(await offScale(page)).toEqual([]);
      });
    }

    for (const route of ROUTES) {
      test(`PRD-18.2 ${route.name}: the page title is the display step, at the page shell's offset`, async ({
        page,
      }) => {
        await page.goto(route.path);
        await page
          .locator("main, [data-testid='stage-frame'], [data-testid='screen-page']")
          .first()
          .waitFor();
        const titles = await page.locator("[data-testid='screen-page'] h1").evaluateAll((els) =>
          els.map((el) => ({
            size: Number.parseFloat(getComputedStyle(el).fontSize),
            // From the top of the page column: the page shell's one offset.
            top: Math.round(
              el.getBoundingClientRect().top -
                (el.closest("[data-testid='screen-page']")?.getBoundingClientRect().top ?? 0),
            ),
          })),
        );
        // The Story, Trace and Inspect screens carry the lens bar and the selection bar above it.
        const lens = ["S-05", "S-10", "S-11"].includes(route.name);
        for (const t of titles) {
          expect(t.size, "h1 size").toBe(h1);
          if (lens) expect(t.top, "h1 offset").toBeGreaterThan(top);
          else expect(t.top, "h1 offset").toBe(top);
        }
      });
    }
  });
}
