// #227 Bundle E1/E2 (Story and Trace lenses) and the carried-over phone targets: level chips and
// the Needs-you mark on Story rows, 14 px Trace rows with a 28 px (44 px on a phone) record
// control, and 44 px lens tabs and level links on a phone. Run with `?speed=100`.
import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { DESKTOP, MOBILE } from "../support/viewports";

const W = "/world/w_village_basic";
const fontPx = (el: Element) => Number.parseFloat(getComputedStyle(el).fontSize);

test("UX-1 E1 Story rows carry a level chip and mark Needs-you rows by bar and label", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}/story?speed=100`);
  const story = page.getByTestId("story-lens");
  await expect(story.locator(".story-list li").first()).toBeVisible({ timeout: 20_000 });
  await expect(story).toContainText("Done: 1 reply sent", { timeout: 20_000 });

  const chip = story.locator(".level-chip").first();
  await expect(chip).toHaveText(/^L\d$/);
  await expect(chip).toHaveAttribute("aria-label", /^Level /);

  const needs = story.locator("li[data-severity='needs_you']").first();
  await expect(needs.locator(".story-flag")).toHaveText("Needs you");
  const bar = await needs.evaluate((el) => getComputedStyle(el).borderLeftWidth);
  expect(bar).toBe("6px");

  const sizes = await story
    .locator(".story-list li:has(.story-meta)")
    .first()
    .evaluate((li) => ({
      text: Number.parseFloat(
        getComputedStyle(li.querySelector(".story-text") as Element).fontSize,
      ),
      meta: Number.parseFloat(
        getComputedStyle(li.querySelector(".story-meta") as Element).fontSize,
      ),
    }));
  expect(sizes).toEqual({ text: 16, meta: 14 });
  expect(problems).toEqual([]);
});

test("UX-1 E2 Trace rows are 14 px and Open record is 28 px high, disabled until a record route exists", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}/trace?speed=100`);
  const rows = page.getByTestId("trace-lens-row");
  await expect(rows).toHaveCount(44, { timeout: 20_000 });
  expect(await rows.first().locator(".trace-top").evaluate(fontPx)).toBe(14);
  const open = page.getByRole("button", { name: /Open record/ }).first();
  await expect(open).toHaveAttribute("aria-disabled", "true"); // no archive route: not invented
  expect((await open.boundingBox())?.height).toBe(28);
  await page.setViewportSize(MOBILE);
  expect((await open.boundingBox())?.height).toBeGreaterThanOrEqual(44);
});

test("UX-1 phone targets: lens tabs and the level link are 44 px high at 390", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize(MOBILE);
  await page.goto(`${W}?speed=100`);
  await page.getByText("World status").click(); // the panels sit in this sheet on a phone
  const tabs = page.locator(".world-panels .lens-tab");
  await expect(tabs.first()).toBeVisible({ timeout: 20_000 });
  for (const tab of await tabs.all()) {
    const box = await tab.boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(44);
  }
  for (const link of await page.locator(".world-panels h2 a").all()) {
    if (!(await link.isVisible())) continue;
    expect((await link.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  }
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}?speed=100`);
  await expect(tabs.first()).toBeVisible({ timeout: 20_000 });
  expect((await tabs.first().boundingBox())?.height).toBe(44);
});

test("UX-1 E3 Inspect shows a building's and an agent's state as a chip, facts and a timeline", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  for (const viewport of [DESKTOP, MOBILE]) {
    await page.setViewportSize(viewport);
    await page.goto(`${W}/inspect/B1?speed=100`);
    const panel = page.getByTestId("inspect-panel");
    await expect(panel).toContainText("State: Finished", { timeout: 20_000 });
    await expect(panel.locator(".inspect-state .btag")).toHaveText("Finished");
    await expect(panel.getByTestId("inspect-facts")).toContainText("People here");
    await expect(panel.getByRole("list", { name: /Events that name this/ })).toBeVisible();
  }
  await page.goto(`${W}/inspect/A_s1?speed=100`);
  const facts = page.getByTestId("inspect-facts");
  await expect(facts).toContainText("Role", { timeout: 20_000 });
  await expect(facts).toContainText("Reports to");
  await expect(facts).toContainText("Now at");
  expect(problems).toEqual([]);
});
