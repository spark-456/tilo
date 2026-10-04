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
  // Nothing has focus on a first load (focus moves only on a route change).
  expect(await page.evaluate(() => document.activeElement?.tagName)).toBe("BODY");
  // Numbers come only from recorded events: the meter ends on the run's 13 of 40 approved credits,
  // and the time saved appears once the run is done, marked an estimate.
  const meter = page.getByTestId("hud-meter");
  await expect(meter).toContainText("Done");
  await expect(meter).toContainText("13");
  await expect(meter).toContainText("credits of 40 approved");
  await expect(meter).toContainText("8 to 18 min");
  await expect(meter).toContainText("estimate");
  await expect(page.getByTestId("needs-count")).toHaveText("0");
  // Rows with role names and state, not raw ids.
  await expect(hud.getByRole("button", { name: /Specialist 1/ })).toContainText("Joined");
  await expect(hud.getByRole("button", { name: /Director/ })).toContainText("Joined");
  // A row selects its object for every lens (FR-WLD-06); the selection bar opens Inspect.
  await hud.getByRole("button", { name: /Mail Room/ }).click();
  await expect(hud.getByRole("link", { name: "Inspect" })).toHaveAttribute(
    "href",
    `${W}/inspect/B1`,
  );
  await expect(hud).not.toContainText("A_dir");
  await expect(page.locator("button.primary")).toHaveCount(1); // UX-1
  await expectNoDeadControls(page, "body");
  await expectAxeClean(page);
  await page.setViewportSize(MOBILE);
  await page.getByText("World status").click();
  await expect(page.getByTestId("hud-meter")).toBeVisible();
  // Escape closes the sheet.
  await page.getByText("World status").focus();
  await page.keyboard.press("Escape");
  await expect(page.locator("details.hud-sheet")).not.toHaveAttribute("open", "");
  expect(problems).toEqual([]);
});

test("S_10 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}/story${FAST}`);
  await expect(page.getByRole("heading", { level: 1, name: "Story" })).toBeVisible();
  await expect(page.getByTestId("story-lens")).toContainText(DONE, { timeout: 15_000 });
  // The severity label is in the story itself (the nav also has a "Needs you" tab).
  await expect(page.getByTestId("story-lens").locator(".story-flag").first()).toHaveText(
    "· Needs you",
  );
  await expect(page.getByTestId("story-lens")).not.toContainText("?speed");
  await expect(page.getByRole("list", { name: "What happened, in order" })).toBeVisible(); // screen-reader Story
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
  // The record and the credits are on screen at 1440 without sideways scroll, in two-line rows.
  const sideways = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(sideways).toBe(false);
  const second = rows.nth(1);
  await expect(second).toContainText("credits");
  await expect(second).toContainText("r_village_basic_1/2");
  const box = await open.boundingBox();
  expect((box?.x ?? 9999) + (box?.width ?? 0)).toBeLessThanOrEqual(DESKTOP.width);
  const heights = await rows.evaluateAll((els) => els.map((e) => e.getBoundingClientRect().height));
  expect(Math.max(...heights), "no double-height blank rows").toBeLessThanOrEqual(70);
  await expectNoDeadControls(page);
  await expectAxeClean(page);
  // At 390 a stacked row still shows the event, actor to target, credits and the record.
  await page.setViewportSize(MOBILE);
  const stacked = rows.nth(1);
  await expect(stacked).toContainText("plan.approaches_proposed");
  await expect(stacked).toContainText("A_dir");
  await expect(stacked).toContainText("credits");
  const record = stacked.getByRole("button", { name: /Open record/ });
  await expect(record).toBeVisible();
  const rb = await record.boundingBox();
  expect((rb?.x ?? 9999) + (rb?.width ?? 0)).toBeLessThanOrEqual(MOBILE.width);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    MOBILE.width,
  );
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
  await expect(page.getByRole("heading", { level: 1, name: "Specialist 1" })).toBeVisible();
  expect(problems).toEqual([]);
});

test("S_05 has its heading while the layout loads, so route-change focus lands on it", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/more?client_delay_ms=1500");
  await page.getByRole("link", { name: "Inspect panel" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Inspect" })).toBeFocused();
  await expect(page.getByRole("heading", { level: 1, name: "Mail Room" })).toBeVisible();
});

test("S_12 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}/delivery${FAST}`);
  await expect(page.getByRole("heading", { level: 1, name: "Delivery" })).toBeVisible();
  const delivery = page.getByTestId("delivery");
  await expect(delivery).toContainText("Finished", { timeout: 15_000 });
  await expect(delivery).toContainText("About 8 to 18 min");
  await expect(delivery).toContainText("estimate"); // PRD 18.4: always marked
  await expect(delivery).toContainText("Triage list");
  // The estimate link sits in the same tile as the time-saved figure.
  const tile = delivery.locator("li", { hasText: "Time saved" });
  await expect(tile.getByRole("link", { name: "How we estimate" })).toHaveAttribute(
    "href",
    "/estimate",
  );
  // Credits agree with the rail, which reads the same events.
  await expect(delivery.locator("li", { hasText: "Credits used" })).toContainText("13");
  await expect(page.getByTestId("hud-meter")).toContainText("13");
  await expect(page.locator("button.primary")).toHaveCount(1); // UX-1
  await expectNoDeadControls(page);
  await expectAxeClean(page);
  await page.setViewportSize(MOBILE);
  await expectAxeClean(page);
  await page.locator("button.primary").click();
  await expect(page.getByRole("heading", { level: 1, name: "Start" })).toBeVisible();
  expect(problems).toEqual([]);
});

test("S_12 says the run is not finished until the log holds world.completed (HR-1)", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}/delivery`); // at the recorded pace: seq 1 only, for the first seconds
  const delivery = page.getByTestId("delivery");
  await expect(delivery).toContainText("has not finished yet");
  await expect(delivery).not.toContainText("Finished");
  await expect(delivery).not.toContainText("Credits used");
  await expect(delivery).not.toContainText("Triage list");
  await expect(page.locator("button.primary")).toHaveCount(1);
});

test("S_12 at 390x844 shows the finished header, the stat tiles and the one primary above the fold", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize(MOBILE);
  await page.goto(`${W}/delivery${FAST}`);
  const delivery = page.getByTestId("delivery");
  await expect(delivery).toContainText("Finished", { timeout: 15_000 });
  const usable = MOBILE.height - 48; // the bottom tabs
  for (const locator of [
    delivery.locator(".delivery-done"),
    delivery.locator("li", { hasText: "Time saved" }),
    delivery.locator("li", { hasText: "Credits used" }),
    page.locator("button.primary"),
  ]) {
    const box = await locator.boundingBox();
    expect((box?.y ?? 9999) + (box?.height ?? 0)).toBeLessThanOrEqual(usable);
  }
  // The Coming soon actions are one compact row.
  const ys = await delivery
    .locator(".action-row button")
    .evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
  expect(ys).toHaveLength(5);
  expect(new Set(ys).size).toBe(1);
  await expect(delivery).toContainText("These actions are coming soon.");
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

// HR-6 (PRD 9.4): whenever the replay is not at its recorded pace, every world screen says so, on
// both viewports, and keeps saying so after a lens link drops ?speed from the address.
const WORLD_PATHS = [W, `${W}/inspect/B1`, `${W}/story`, `${W}/trace`, `${W}/delivery`];
for (const viewport of [DESKTOP, MOBILE]) {
  for (const path of WORLD_PATHS) {
    test(`HR_6 ${path.replace(W, "world") || "world"} shows the replay speed badge at ${viewport.width}x${viewport.height}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await page.goto(`${path}?speed=20`);
      await expect(page.getByTestId("speed-badge")).toHaveText("Replay at 20× speed");
      await expect(page.getByTestId("speed-badge")).toBeVisible();
    });
  }
  test(`HR_6 the badge stays after lens navigation drops ?speed at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto(`${W}/story?speed=20`);
    await page.getByRole("link", { name: "Trace" }).first().click();
    expect(page.url()).not.toContain("speed");
    await expect(page.getByRole("heading", { level: 1, name: "Trace" })).toBeVisible();
    await expect(page.getByTestId("speed-badge")).toHaveText("Replay at 20× speed");
  });
  test(`HR_6 no badge at the recorded pace at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto(`${W}/story`);
    await expect(page.getByRole("heading", { level: 1, name: "Story" })).toBeVisible();
    await expect(page.getByTestId("speed-badge")).toHaveCount(0);
  });
}

// UX-1: with a slow client and events arriving, nothing on S-04, S-05, S-10, S-11 or S-12 moves.
const SETTLED: ReadonlyArray<readonly [string, string, string]> = [
  ["S_04", W, "credits of 40 approved"],
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
      // S-04 is in a closed sheet on mobile, so attached rather than visible.
      await expect(page.getByText(settled).first()).toBeAttached({ timeout: 20_000 });
      await page.waitForTimeout(300); // let a late shift be reported
      const shifts = await page.evaluate(
        () => (window as unknown as { __shifts: number[] }).__shifts,
      );
      expect(shifts).toEqual([]);
    });
  }
}
