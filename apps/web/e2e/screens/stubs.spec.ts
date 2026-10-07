// AGW-08 smoke: one test per "Coming soon" screen (PRD 18.3). Group B replaces a stub's test with
// the real screen's own when it builds the screen. Names carry the screen id.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { SCREENS } from "../../src/screens/meta";
import { expectNoDeadControls, watchConsole } from "../support/screens";
import { DESKTOP, MOBILE } from "../support/viewports";

const STUBS: ReadonlyArray<readonly [string, string, string]> = [];

for (const [id, path, name] of STUBS) {
  test(`${id} renders, no console errors, placeholders aria-disabled`, async ({ page }) => {
    test.setTimeout(90_000); // two viewports and an axe run, under a parallel suite
    const problems = watchConsole(page);
    for (const viewport of [DESKTOP, MOBILE]) {
      await page.setViewportSize(viewport);
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
      await expect(page.getByTestId("coming-soon")).toContainText("Coming soon");
      await expect(page.getByTestId("fixture-replay-banner")).toBeVisible();
      await expectNoDeadControls(page);
    }
    const axe = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag22aa"])
      .analyze();
    expect(axe.violations).toEqual([]);
    expect(problems).toEqual([]);
  });

  // UX-1: a cold load must not move the title or what is below it when the h1 face arrives.
  for (const viewport of [DESKTOP, MOBILE]) {
    test(`${id} UX_1 has zero layout shifts on a cold load at ${viewport.width}x${viewport.height}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await page.addInitScript(() => {
        const w = window as unknown as { __shifts: number[] };
        w.__shifts = [];
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries())
            w.__shifts.push((entry as unknown as { value: number }).value);
        }).observe({ type: "layout-shift", buffered: true });
      });
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
      await page.waitForTimeout(500); // let a late font swap be reported
      const shifts = await page.evaluate(
        () => (window as unknown as { __shifts: number[] }).__shifts,
      );
      expect(shifts).toEqual([]);
    });
  }
}

test("AGW-08 /screens lists every screen id with built or placeholder status and a link", async ({
  page,
}) => {
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto("/screens");
  await expect(page.getByRole("heading", { level: 1, name: "Screens" })).toBeVisible();
  const rows = page.locator("tbody tr");
  await expect(rows).toHaveCount(SCREENS.length);
  await expect(rows.first()).toContainText("S-01");
  await expect(rows.last()).toContainText(SCREENS.at(-1)?.id ?? "");
  // Each linked screen opens: follow the S-13 link.
  await page.getByRole("link", { name: "Library and Memory Vault" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Library" })).toBeVisible();
  expect(page.url()).toMatch(/\/library$/);
  expect(problems).toEqual([]);
});

test("AGW-08 More reaches every screen the tabs do not, and nav links navigate", async ({
  page,
}) => {
  const problems = watchConsole(page);
  await page.setViewportSize(MOBILE);
  await page.goto("/needs-you"); // WEB-CUTOVER: "/" is the Park Home, which has its own nav
  const nav = page.getByRole("navigation", { name: /primary/i });
  await nav.getByRole("link", { name: "More" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "More" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "More" })).toHaveAttribute("aria-current", "page");
  // Each row is a 44 px target (PRD 18.3 mobile).
  const rows = page.locator(".screen-list a");
  for (let i = 0; i < (await rows.count()); i++) {
    const box = await rows.nth(i).boundingBox();
    expect(box?.height ?? 0, `More row ${i}`).toBeGreaterThanOrEqual(44);
  }
  await page.getByRole("link", { name: "Autonomy" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Autonomy" })).toBeVisible();
  await nav.getByRole("link", { name: "Library" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Library" })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { level: 1, name: "Autonomy" })).toBeVisible();
  expect(problems).toEqual([]);
});
