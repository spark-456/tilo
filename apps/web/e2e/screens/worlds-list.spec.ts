// S-14 Worlds list (Bundle G1, PRD 18.3, HR-4): a real search and status filters with counts,
// a thumbnail drawn from the world's own layout, honest empty states, and no layout shift.
import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { DESKTOP, MOBILE } from "../support/viewports";

const TITLE = "Triage my inbox and answer the supplier about Thursday";

test("S_14 G1 filter chips carry counts from the one recorded world, Scheduled is a true zero", async ({
  page,
}) => {
  test.setTimeout(90_000); // the first test after a cold Vite start compiles the app
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto("/worlds?speed=100");
  const card = page.getByTestId("world-card");
  await expect(card).toContainText("Finished", { timeout: 15_000 });
  await expect(page.getByTestId("count-all")).toHaveText("1");
  await expect(page.getByTestId("count-finished")).toHaveText("1");
  await expect(page.getByTestId("count-running")).toHaveText("0");
  await expect(page.getByTestId("count-scheduled")).toHaveText("0");
  await expect(page.getByRole("radio", { name: /^All/ })).toBeChecked();

  await page.getByRole("radio", { name: /^Scheduled/ }).check({ force: true });
  await expect(page.getByTestId("worlds-filter-empty")).toContainText("Nothing is scheduled");
  await expect(card).toHaveCount(0);

  await page.getByRole("radio", { name: /^Finished/ }).check({ force: true });
  await expect(card).toBeVisible();
  expect(problems).toEqual([]);
});

test("S_14 G1 search narrows the list and says so when nothing matches", async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/worlds?speed=100");
  const card = page.getByTestId("world-card");
  await expect(card).toContainText(TITLE, { timeout: 15_000 });
  const search = page.getByRole("searchbox", { name: "Search worlds" });
  await search.fill("supplier");
  await expect(card).toBeVisible();
  await search.fill("zzz");
  await expect(page.getByTestId("worlds-filter-empty")).toContainText(
    "No world matches that search",
  );
  await expect(page.getByTestId("count-all")).toHaveText("0");
  await search.fill("");
  await expect(card).toBeVisible();
});

test("S_14 G1 the thumbnail is the world's own layout, and the HR-4 banner and replay note stay", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/worlds?speed=100");
  const card = page.getByTestId("world-card");
  await expect(card.locator(".world-thumb svg polygon").first()).toBeAttached();
  await expect(card.locator(".world-thumb svg polygon")).not.toHaveCount(4); // not the old fixed cube
  await expect(page.getByTestId("fixture-replay-banner")).toBeVisible();
  await expect(page.getByTestId("replay-note")).toContainText("Replay of run #village_basic_1");
});

for (const [name, viewport] of [
  ["desktop", DESKTOP],
  ["mobile", MOBILE],
] as const) {
  test(`S_14 G1 the card and filters do not move while events arrive (${name})`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.addInitScript(() => {
      const w = window as unknown as { __cls: number };
      w.__cls = 0;
      new PerformanceObserver((list) => {
        for (const e of list.getEntries()) {
          const s = e as PerformanceEntry & { value: number; hadRecentInput: boolean };
          if (!s.hadRecentInput) w.__cls += s.value;
        }
      }).observe({ type: "layout-shift", buffered: true });
    });
    await page.goto("/worlds?speed=100");
    await expect(page.getByTestId("world-card")).toContainText("Finished", { timeout: 15_000 });
    expect(await page.evaluate(() => (window as unknown as { __cls: number }).__cls)).toBe(0);
    const doc = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(doc).toBeLessThanOrEqual(viewport.width);
  });
}

test("S_14 G1 the status chips are 44 px high on a phone and 36 px on a desktop", async ({
  page,
}) => {
  test.setTimeout(90_000);
  for (const [viewport, min] of [
    [MOBILE, 44],
    [DESKTOP, 36],
  ] as const) {
    await page.setViewportSize(viewport);
    await page.goto("/worlds?speed=100");
    await expect(page.getByTestId("world-card")).toBeVisible({ timeout: 20_000 });
    for (const radio of await page.getByRole("radio").all()) {
      const box = await radio.boundingBox(); // the radio fills its chip: this is the hit area
      expect(box?.height).toBeGreaterThanOrEqual(min);
    }
  }
});
