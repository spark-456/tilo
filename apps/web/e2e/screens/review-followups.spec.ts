// Frontend follow-ups from the AGW-01/AGW-08 reviews (PRs #129 to #143) and issue #43: the HR-6
// badge (words, status region, clamped value, no overlap), Not found for unknown addresses, focus,
// 44 px mobile targets, the S-12 tiles and the right rail on screens that show the run.
import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { DESKTOP, MOBILE } from "../support/viewports";

const W = "/world/w_village_basic";
const FAST = "?speed=100";
const NARROW = { width: 320, height: 640 } as const;

type Box = { x: number; y: number; width: number; height: number };
async function box(locator: Locator): Promise<Box> {
  const b = await locator.boundingBox();
  if (!b) throw new Error("element has no box");
  return b;
}
const overlaps = (a: Box, b: Box): boolean =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

async function axeBestPractice(page: Page) {
  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag22aa", "best-practice"])
    .analyze();
  return axe.violations;
}

// ---- HR-6 speed badge -------------------------------------------------------------------------

for (const viewport of [DESKTOP, MOBILE, NARROW]) {
  test(`HR_6 the badge is words in a status region and overlaps nothing at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto(`${W}/story?speed=20`);
    const badge = page.getByTestId("speed-badge");
    await expect(badge).toHaveText("Replay at 20× speed");
    await expect(badge).toHaveAttribute("role", "status");
    const font = await badge.evaluate((el) => getComputedStyle(el).fontFamily);
    expect(font, "the UI face, not the mono face").not.toMatch(/mono/i);
    const b = await box(badge);
    const banner = await box(page.getByTestId("fixture-replay-banner"));
    const heading = await box(page.getByRole("heading", { level: 1, name: "Story" }));
    expect(overlaps(b, banner), "badge over the fixture banner").toBe(false);
    expect(overlaps(b, heading), "badge over the page heading").toBe(false);
    expect(b.x).toBeGreaterThanOrEqual(0);
    expect(b.x + b.width).toBeLessThanOrEqual(viewport.width);
  });
}

for (const viewport of [DESKTOP, MOBILE]) {
  test(`HR_6 the badge has no axe finding, best-practice region included, at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto(`${W}/story?speed=20`);
    await expect(page.getByTestId("speed-badge")).toBeVisible();
    expect(await axeBestPractice(page)).toEqual([]);
  });
}

test("HR_6 an extreme ?speed= shows a clamped, rounded value (#43)", async ({ page }) => {
  const problems = watchConsole(page);
  await page.goto(`${W}/trace?speed=1e-300`);
  await expect(page.getByTestId("speed-badge")).toHaveText("Replay at 0.1× speed");
  await page.goto(`${W}/trace?speed=1e308`);
  await expect(page.getByTestId("speed-badge")).toHaveText("Replay at 1000× speed");
  await page.goto(`${W}/trace?speed=2.456789`);
  await expect(page.getByTestId("speed-badge")).toHaveText("Replay at 2.46× speed");
  expect(problems).toEqual([]);
});

test("HR_6 the stage fixture player clamps and words its badge too (#43)", async ({ page }) => {
  const problems = watchConsole(page);
  await page.goto("/?fixture=village-basic&speed=1e308");
  await expect(page.getByTestId("speed-badge")).toHaveText("Replay at 1000× speed");
  await expect(page.getByTestId("speed-badge")).toHaveAttribute("role", "status");
  expect(problems).toEqual([]);
});

// ---- Not found --------------------------------------------------------------------------------

const UNKNOWN_WORLDS = [
  "/world/nope",
  "/world/nope/story",
  "/world/nope/trace",
  "/world/nope/delivery",
  "/world/nope/inspect/B1",
  "/world/x%2Fy/trace",
];
const EXTRA_SEGMENTS = [
  `${W}/inspect/B1/x`,
  `${W}/inspect/B1//`,
  `${W}/inspect`,
  `${W}/nope`,
  "/task/t/nope",
];
for (const path of [...UNKNOWN_WORLDS, ...EXTRA_SEGMENTS]) {
  test(`HR_1 ${path} says Not found and shows no run`, async ({ page }) => {
    const problems = watchConsole(page);
    await page.goto(`${path}${FAST.replace("?", path.includes("?") ? "&" : "?")}`);
    await expect(page.getByRole("heading", { level: 1, name: "Not found" })).toBeVisible();
    await expect(page.getByTestId("not-found")).toBeVisible();
    // Nothing of the village run, and not the Start screen either.
    for (const id of ["story-lens", "trace-lens", "delivery", "inspect-panel", "world-hud"]) {
      await expect(page.getByTestId(id)).toHaveCount(0);
    }
    await expect(page.getByTestId("flow-shell")).toHaveCount(0);
    await expect(page.getByTestId("speed-badge")).toHaveCount(0);
    await page.waitForTimeout(500); // a run that started anyway would have events by now
    await expect(page.locator("body")).not.toContainText("credits of 40 approved");
    await expect(page.locator("body")).not.toContainText("Mail Room");
    expect(problems).toEqual([]);
  });
}

test("HR_1 Not found offers the way back, and the known world still works", async ({ page }) => {
  await page.goto("/world/nope/story");
  await page.getByRole("link", { name: "Back to Start" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Start" })).toBeVisible();
  await page.goto(`${W}/story${FAST}`);
  await expect(page.getByRole("heading", { level: 1, name: "Story" })).toBeVisible();
  await expect(page.getByTestId("story-lens")).toContainText("Done: 1 reply sent", {
    timeout: 15_000,
  });
});

test("HR_1 Not found has no axe finding, best-practice included, on both viewports", async ({
  page,
}) => {
  for (const viewport of [DESKTOP, MOBILE]) {
    await page.setViewportSize(viewport);
    await page.goto("/world/nope/story");
    await expect(page.getByRole("heading", { level: 1, name: "Not found" })).toBeVisible();
    expect(await axeBestPractice(page)).toEqual([]);
  }
});

// ---- Focus ------------------------------------------------------------------------------------

test("PRD-17.5 Escape closes the mobile HUD sheet and focus returns to its summary", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE);
  await page.goto(`${W}${FAST}`);
  const summary = page.getByText("World status");
  await summary.click();
  const inside = page.locator("details.hud-sheet a").first();
  await inside.focus();
  await expect(inside).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator("details.hud-sheet")).not.toHaveAttribute("open", "");
  await expect(summary).toBeFocused();
});

test("PRD-17.5 the World lens takes focus on its h1 after lens navigation, like Story and Trace", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}/story${FAST}`);
  await page.getByRole("navigation", { name: "Lens" }).getByRole("link", { name: "World" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "World" })).toBeFocused();
  await page.getByRole("navigation", { name: "Lens" }).getByRole("link", { name: "Trace" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Trace" })).toBeFocused();
  await page
    .getByRole("navigation", { name: "Primary" })
    .getByRole("link", { name: "World" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "World" })).toBeFocused();
});

// ---- 44 px mobile targets, S-12 tiles --------------------------------------------------------

test("PRD-17.5 S-11 Open record is a 44 px target at 390", async ({ page }) => {
  await page.setViewportSize(MOBILE);
  await page.goto(`${W}/trace${FAST}`);
  await expect(page.getByTestId("trace-lens-row")).toHaveCount(44, { timeout: 15_000 });
  const buttons = page.getByRole("button", { name: /Open record/ });
  expect(await buttons.count()).toBeGreaterThan(0);
  for (const b of await buttons.all()) {
    const { width, height } = await box(b);
    expect(height).toBeGreaterThanOrEqual(44);
    expect(width).toBeGreaterThanOrEqual(44);
  }
});

test("PRD-17.5 S-05 Back to the world is a 44 px target at 390 and 24 px on desktop", async ({
  page,
}) => {
  for (const [viewport, min] of [
    [MOBILE, 44],
    [DESKTOP, 24],
  ] as const) {
    await page.setViewportSize(viewport);
    await page.goto(`${W}/inspect/B1`);
    const link = page.getByRole("link", { name: "Back to the world" });
    await expect(link).toBeVisible();
    const { width, height } = await box(link);
    expect(height).toBeGreaterThanOrEqual(min);
    expect(width).toBeGreaterThanOrEqual(min);
  }
});

for (const viewport of [MOBILE, NARROW]) {
  test(`PRD-17.5 S-12 compact actions are 44 px targets and the stat tiles are not cramped at ${viewport.width}`, async ({
    page,
  }) => {
    test.setTimeout(60_000);
    await page.setViewportSize(viewport);
    await page.goto(`${W}/delivery${FAST}`);
    const delivery = page.getByTestId("delivery");
    await expect(delivery).toContainText("Finished", { timeout: 15_000 });
    const actions = delivery.locator(".action-row button");
    expect(await actions.count()).toBe(5);
    for (const a of await actions.all()) {
      const { width, height } = await box(a);
      expect(height).toBeGreaterThanOrEqual(44);
      expect(width).toBeGreaterThanOrEqual(44);
    }
    // Time saved across the top, Credits used and Deliverables two-up below it.
    const time = await box(delivery.locator("li", { hasText: "Time saved" }));
    const credits = await box(delivery.locator("li", { hasText: "Credits used" }));
    const count = await box(delivery.locator("li", { hasText: "Deliverables" }).first());
    expect(credits.y).toBeGreaterThanOrEqual(time.y + time.height - 1);
    expect(Math.abs(credits.y - count.y)).toBeLessThanOrEqual(1);
    expect(time.width).toBeGreaterThanOrEqual(viewport.width - 64);
    expect(credits.width).toBeGreaterThanOrEqual(viewport.width / 2 - 40);
    // The estimate link is a 44 px target and fits on one line.
    const link = await box(delivery.getByRole("link", { name: "How we estimate" }));
    expect(link.height).toBeGreaterThanOrEqual(44);
    expect(link.width).toBeGreaterThanOrEqual(44);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      viewport.width,
    );
  });
}

// ---- Right rail on screens that show the run --------------------------------------------------

const RUN_PAGES = [
  "/library",
  "/worlds",
  "/autonomy",
  "/channels",
  "/mail",
  "/team",
  "/connections",
  "/library/artifacts",
  "/estimate",
];
for (const path of RUN_PAGES) {
  test(`UX_1 ${path} right rail describes the same run as the page, never "Nothing yet" while it shows one`, async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP);
    await page.addInitScript(() => {
      const w = window as unknown as { __shifts: number[] };
      w.__shifts = [];
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries())
          w.__shifts.push((entry as unknown as { value: number }).value);
      }).observe({ type: "layout-shift", buffered: true });
    });
    await page.goto(`${path}${FAST}`);
    const rail = page.getByTestId("right-rail");
    await expect(rail).toContainText("credits of 40 approved", { timeout: 20_000 });
    await expect(rail).toContainText("Done");
    await expect(rail).not.toContainText("Nothing yet");
    await expect(rail).not.toContainText("No agents assigned");
    await page.waitForTimeout(300);
    const shifts = await page.evaluate(
      () => (window as unknown as { __shifts: number[] }).__shifts,
    );
    expect(shifts).toEqual([]);
  });
}

test("UX_1 screens that show no run keep the honest empty rail", async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  for (const path of ["/", "/more", "/needs-you"]) {
    await page.goto(path);
    await expect(page.getByTestId("right-rail")).toContainText("Nothing yet");
  }
});
