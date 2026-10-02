// AGW-08 group A smoke: S-04, S-05, S-10, S-11 and S-12 on the fixture client (PRD 18.3). Each test
// name carries the screen id. `?speed=100` fast-forwards the recorded replay (about 2 s in all).
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { expectNoDeadControls, watchConsole } from "../support/screens";
import { DESKTOP, MOBILE } from "../support/viewports";

const W = "/world/w_village_basic";
const FAST = "?speed=100";
const DONE = "Done: 1 reply sent and 12 emails triaged for 13 credits.";

async function expectAxeClean(page: Page) {
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag22aa"]).analyze();
  expect(axe.violations).toEqual([]);
}

test("S_04 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}${FAST}`);
  const hud = page.getByTestId("world-hud");
  await expect(page.getByRole("heading", { level: 1, name: "World" })).toBeVisible();
  await expect(page.getByTestId("stage-frame")).toHaveAttribute("data-stage-ready", "true");
  // Numbers come only from recorded events: the meter ends on the run's 13 credits.
  await expect(page.getByTestId("hud-meter")).toHaveText("Done Credits used so far: 13");
  await expect(hud.getByRole("link", { name: "Story" })).toBeVisible();
  await expect(hud.getByRole("link", { name: "Mail Room" })).toHaveAttribute(
    "href",
    `${W}/inspect/B1`,
  );
  await expect(page.locator("button.primary")).toHaveCount(1); // UX-1
  await expectNoDeadControls(page, "body");
  await expectAxeClean(page);
  await page.setViewportSize(MOBILE);
  await page.getByText("World status").click();
  await expect(page.getByTestId("hud-meter")).toBeVisible();
  expect(problems).toEqual([]);
});

test("S_10 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}/story${FAST}`);
  await expect(page.getByRole("heading", { level: 1, name: "Story" })).toBeVisible();
  await expect(page.getByTestId("story-lens")).toContainText(DONE, { timeout: 15_000 });
  await expect(page.getByText("Needs you", { exact: false }).first()).toBeVisible();
  await expect(page.getByRole("log")).toBeVisible(); // screen-reader Story
  await expectNoDeadControls(page);
  await expectAxeClean(page);
  await page.setViewportSize(MOBILE);
  await expectAxeClean(page);
  expect(problems).toEqual([]);
});

test("S_11 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}/trace${FAST}`);
  await expect(page.getByRole("heading", { level: 1, name: "Trace" })).toBeVisible();
  const rows = page.getByTestId("trace-lens-row");
  await expect(rows).toHaveCount(44, { timeout: 15_000 });
  await expect(rows.first()).toContainText("world.requested");
  // The raw-record viewer is a placeholder: visible, labelled, aria-disabled.
  const open = page.getByRole("button", { name: /Open record/ }).first();
  await expect(open).toHaveAttribute("aria-disabled", "true");
  await expect(open).toHaveAttribute("title", "Coming soon");
  await expectNoDeadControls(page);
  await expectAxeClean(page);
  expect(problems).toEqual([]);
});

test("S_05 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}/inspect/B1${FAST}`);
  await expect(page.getByRole("heading", { level: 1, name: "Mail Room" })).toBeVisible();
  await expect(page.getByTestId("inspect-panel")).toContainText("State: Finished", {
    timeout: 15_000,
  });
  await expect(page.getByText("Mail Room is planned.")).toBeVisible();
  await expectNoDeadControls(page);
  await expectAxeClean(page);
  await page.goto(`${W}/inspect/B99`);
  await expect(page.getByRole("heading", { level: 1, name: "Not found" })).toBeVisible();
  await page.setViewportSize(MOBILE);
  await page.goto(`${W}/inspect/A_s1`);
  await expect(page.getByTestId("inspect-panel")).toContainText("specialist A_s1");
  expect(problems).toEqual([]);
});

test("S_12 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}/delivery`);
  await expect(page.getByRole("heading", { level: 1, name: "Delivery" })).toBeVisible();
  const delivery = page.getByTestId("delivery");
  await expect(delivery).toContainText("About 8 to 18 min");
  await expect(delivery).toContainText("estimate"); // PRD 18.4: always marked
  await expect(delivery).toContainText("Triage list");
  await expect(page.getByRole("link", { name: "How we estimate time saved" })).toHaveAttribute(
    "href",
    "/estimate",
  );
  await expect(page.locator("button.primary")).toHaveCount(1); // UX-1
  await expectNoDeadControls(page);
  await expectAxeClean(page);
  await page.setViewportSize(MOBILE);
  await expectAxeClean(page);
  await page.locator("button.primary").click();
  await expect(page.getByRole("heading", { level: 1, name: "Start" })).toBeVisible();
  expect(problems).toEqual([]);
});

test("S_04 lens tabs and the outline reach Story, Trace and Inspect", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}${FAST}`);
  const hud = page.getByTestId("world-hud");
  await hud.getByRole("link", { name: "Story" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Story" })).toBeVisible();
  // The replay was already running, so it is not restarted by moving between lenses.
  await expect(page.getByTestId("story-lens")).toContainText(DONE, { timeout: 15_000 });
  await page.getByRole("link", { name: "Trace" }).first().click();
  await expect(page.getByTestId("trace-lens-row")).toHaveCount(44);
  await page.getByRole("link", { name: "World" }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "World" })).toBeVisible();
});

// UX-1: with a slow client and events arriving, nothing on S-04, S-05, S-10, S-11 or S-12 moves.
const SETTLED: ReadonlyArray<readonly [string, string, string]> = [
  ["S_04", W, "Done Credits used so far: 13"],
  ["S_10", `${W}/story`, DONE],
  ["S_11", `${W}/trace`, "world.completed"],
  ["S_05", `${W}/inspect/B1`, "State: Finished"],
  ["S_12", `${W}/delivery`, "Triage list"],
];
for (const viewport of [DESKTOP, MOBILE]) {
  for (const [id, path, settled] of SETTLED) {
    test(`${id} UX_1 has zero layout shifts while a slow client answers at ${viewport.width}x${viewport.height}`, async ({
      page,
    }) => {
      test.setTimeout(60_000);
      await page.setViewportSize(viewport);
      await page.addInitScript(() => {
        const w = window as unknown as { __shifts: number[] };
        w.__shifts = [];
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries())
            w.__shifts.push((entry as unknown as { value: number }).value);
        }).observe({ type: "layout-shift", buffered: true });
      });
      await page.goto(`${path}?client_delay_ms=800&speed=100`, { waitUntil: "commit" });
      await expect(page.getByText(settled).first()).toBeAttached({ timeout: 20_000 }); // S-04 is in a closed sheet on mobile
      await page.waitForTimeout(300); // let a late shift be reported
      const shifts = await page.evaluate(
        () => (window as unknown as { __shifts: number[] }).__shifts,
      );
      expect(shifts).toEqual([]);
    });
  }
}
