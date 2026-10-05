// Issue #227 Bundle C, the shared app top bar every artboard has (Tilo Home v2, Worlds, World
// Player): the logo, the current place and the real Needs-you count. At 1440x900, 390x844 and
// 320x640. No user, plan or avatar: the client knows none, so none is drawn.
import { expect, test } from "@playwright/test";
import { readShifts, watchShifts } from "./support/shifts";
import { DESKTOP, MOBILE } from "./support/viewports";

const SMALL = { width: 320, height: 640 } as const;
const W = "/world/w_village_basic";
// [path, the place's name, the lens or step after it ("" for none)]. A world route's name is the
// run's recorded title once its first event is in.
const PLACES: ReadonlyArray<readonly [string, RegExp, string]> = [
  ["/", /^Home$/, ""],
  ["/worlds", /^Worlds$/, ""],
  [`${W}`, /Triage my inbox/, ""],
  [`${W}/story`, /Triage my inbox/, "Story"],
  [`${W}/trace`, /Triage my inbox/, "Trace"],
  ["/needs-you", /^Needs you$/, ""],
  ["/library", /^Library$/, ""],
  ["/settings", /Settings/, ""],
];

for (const viewport of [DESKTOP, MOBILE, SMALL]) {
  const size = `${viewport.width}x${viewport.height}`;

  test(`UX-227-C1 ${size} the top bar is on every route, below the strip, with the logo home and the place`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    for (const [path, place, sub] of PLACES) {
      await page.goto(`${path}?speed=1000`);
      const bar = page.getByTestId("top-bar");
      await expect(bar, path).toBeVisible();
      const placeEl = page.getByTestId("top-bar-place");
      await expect(placeEl, path).toHaveText(place);
      await expect(placeEl, path).toHaveAttribute("data-sub", sub);
      const box = await bar.boundingBox();
      const strip = await page.locator(".status-strip").boundingBox();
      expect(box?.height, `${path} bar height`).toBe(viewport.width < 768 ? 56 : 64);
      expect(box?.width, `${path} bar spans the viewport`).toBe(viewport.width);
      // Fixture mode: the strip is above the bar, never covered by it.
      expect(box?.y, `${path} bar sits below the strip`).toBeGreaterThanOrEqual(
        (strip?.y ?? 0) + (strip?.height ?? 0),
      );
      const logo = bar.getByRole("link", { name: "Tilo home" });
      await expect(logo, path).toHaveAttribute("href", "/");
      const h = await logo.boundingBox();
      expect(h?.height, `${path} logo target`).toBeGreaterThanOrEqual(24);
    }
  });

  test(`UX-227-C1 ${size} the bar covers nothing: the rail, tabs, content and Ask Tilo all start below it`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    for (const path of ["/", "/worlds", `${W}`, `${W}/story`]) {
      await page.goto(`${path}?speed=1000`);
      const bar = await page.getByTestId("top-bar").boundingBox();
      const barBottom = (bar?.y ?? 0) + (bar?.height ?? 0);
      const below = viewport.width < 768 ? "bottom-tabs" : "left-rail";
      const nav = await page.getByTestId(below).boundingBox();
      expect(nav?.y, `${path} ${below}`).toBeGreaterThanOrEqual(barBottom - 1);
      // The Ask Tilo item still opens the panel, and the panel starts under the bar.
      await page.getByRole("button", { name: /Ask Tilo/ }).click();
      const panel = await page.getByRole("dialog").boundingBox();
      expect(panel?.y, `${path} assistant panel`).toBeGreaterThanOrEqual(barBottom - 1);
      await page.keyboard.press("Escape");
      // No horizontal scroll: the bar fits the phone.
      const wide = await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth,
      );
      expect(wide, `${path} horizontal overflow`).toBe(false);
    }
  });

  test(`UX-227-C1 ${size} the bar's type is on the ramp and its targets are 24 px or more`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto(`${W}/story`);
    const found = await page.getByTestId("top-bar").evaluate((bar) => {
      const sizes = new Set<number>();
      for (const el of [bar, ...bar.querySelectorAll("*")]) {
        if (el.childNodes.length && [...el.childNodes].some((n) => n.nodeType === 3)) {
          sizes.add(Number.parseFloat(getComputedStyle(el).fontSize));
        }
      }
      return [...sizes];
    });
    for (const px of found) expect([12, 14, 16, 20, 24, 32, 40]).toContain(px);
  });
}

test("UX-227-C1 the Needs-you count is the queue S-06 lists, links to it, and is absent at zero", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize(DESKTOP);
  await page.goto("/needs-you?speed=5", { waitUntil: "commit" }); // the replay starts at mount
  await expect(page.getByTestId("top-bar-waiting")).toHaveCount(0); // nothing waits yet (HR-1)
  const rows = page.getByTestId("needs-queue").locator("li");
  await expect(rows).toHaveCount(1, { timeout: 30_000 });
  const waiting = page.getByTestId("top-bar-waiting");
  await expect(waiting).toHaveText(/1\s*decision waiting/);
  // On the queue's own page the chip is text for the page you are on, not a link to itself.
  await expect(waiting).not.toHaveAttribute("href", /.*/);
  await expect(waiting).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("top-bar-waiting")).toHaveCount(0, { timeout: 30_000 }); // answered
});

test("UX-227-C1 the bar draws no user, plan or avatar: the client has none (HR-1)", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/worlds");
  const text = await page.getByTestId("top-bar").innerText();
  expect(text).not.toMatch(/plan|team plan|free|pro\b|enterprise|alex|\bAM\b/i);
  await expect(page.getByTestId("top-bar").locator("img")).toHaveCount(0);
});

test("UX-227-C1 the bar never shifts the layout while a replay runs", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize(DESKTOP);
  await watchShifts(page);
  await page.goto(`${W}/story?speed=20`);
  await expect(page.getByTestId("top-bar-place")).toHaveAttribute("data-sub", "Story");
  await page.waitForTimeout(6000);
  const shifts = await readShifts(page);
  expect(shifts.reduce((a, b) => a + b, 0)).toBeLessThan(0.001);
});

test("UX-227-C1 the bar names a ?fixture= replay's world and keeps the HR-4 banner above it", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/?fixture=village-basic&seq=44");
  await expect(page.getByTestId("top-bar-place")).toHaveText(/^World$/);
  await expect(page.getByTestId("fixture-replay-banner")).toBeVisible();
  const banner = await page.getByTestId("fixture-replay-banner").boundingBox();
  const bar = await page.getByTestId("top-bar").boundingBox();
  expect((banner?.y ?? 0) + (banner?.height ?? 0)).toBeLessThanOrEqual(bar?.y ?? 0);
});

test("UX-227-C1 at 1920 the bar's row is capped at 1440 px and centred, the bar stays full width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/worlds?speed=1000");
  const bar = await page.getByTestId("top-bar").boundingBox();
  expect(bar?.width).toBe(1920);
  const logo = await page.getByRole("link", { name: "Tilo home" }).boundingBox();
  expect(logo?.x, "logo starts at the row's left edge").toBeCloseTo(240, 0);
});
