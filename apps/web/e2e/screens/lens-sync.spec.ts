// FR-WLD-06: World, Story and Trace in sync, Inspect on every object (PRD 9.6, 18.3).
// Acceptance: selecting an agent highlights it in all three lenses in <= 200 ms.
//
// DOM contract for this ticket:
//   [data-testid="selection-bar"]  names the selection (or says nothing is selected), links to its
//                                  Inspect screen and has a Clear button; on every lens screen.
//   World lens: HUD roster rows are buttons with aria-pressed; the stage frame gets
//                                  data-selected="<id>" and draws a ring (a static outline).
//   Story and Trace: a row that names the selection has data-selected="true"; an actor or target
//                                  that can be selected is a button.
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { DESKTOP, MOBILE } from "../support/viewports";

const W = "/world/w_village_basic";
const FAST = "?speed=100";
const A_S1_SEQS = [14, 18, 19, 20, 21, 22, 23, 24, 25, 27, 40];

const hudRow = (page: Page, name: RegExp) =>
  page.getByTestId("world-hud").getByRole("button", { name });
const highlightedSeqs = (page: Page, rows: string) =>
  page
    .locator(`${rows}[data-selected="true"]`)
    .evaluateAll((els) => els.map((el) => Number(el.getAttribute("data-seq"))));
const lens = (page: Page, name: string) =>
  page.getByRole("navigation", { name: "Lens" }).getByRole("link", { name });
const finished = (page: Page) =>
  expect(page.getByTestId("hud-meter")).toContainText("Done", { timeout: 15_000 });

/** Milliseconds from the next click until every selector matches (frame by frame). */
async function msUntil(page: Page, click: () => Promise<void>, selectors: string[]) {
  await page.evaluate((all) => {
    const w = window as unknown as { __ms: number | undefined };
    w.__ms = undefined;
    document.addEventListener(
      "click",
      () => {
        const t0 = performance.now();
        const poll = () => {
          if (all.every((s) => document.querySelector(s))) w.__ms = performance.now() - t0;
          else requestAnimationFrame(poll);
        };
        poll();
      },
      { capture: true, once: true },
    );
  }, selectors);
  await click();
  await page.waitForFunction(() => (window as unknown as { __ms?: number }).__ms !== undefined);
  return page.evaluate(() => (window as unknown as { __ms: number }).__ms);
}

test("FR_WLD_06 a selection made in the World lens follows to Story and Trace", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}${FAST}`);
  await finished(page);
  await page.evaluate(() => {
    (window as unknown as { __kept: boolean }).__kept = true;
  });
  await expect(page.getByTestId("selection-bar")).toContainText("Choose anything to inspect it");
  await hudRow(page, /Specialist 1/).click();
  await expect(hudRow(page, /Specialist 1/)).toHaveAttribute("aria-pressed", "true");
  await expect(hudRow(page, /Director/)).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByTestId("selection-bar")).toContainText("Specialist 1");

  await lens(page, "Story").click();
  await expect(page.getByTestId("story-lens")).toContainText("Specialist 1");
  await expect(page.locator('[data-testid="story-lens"] li[data-seq]')).toHaveCount(44);
  expect(await highlightedSeqs(page, "[data-testid=story-lens] li")).toEqual(A_S1_SEQS);
  await expect(hudRow(page, /Specialist 1/)).toHaveAttribute("aria-pressed", "true");

  await lens(page, "Trace").click();
  await expect(page.getByTestId("trace-lens-row")).toHaveCount(44);
  expect(await highlightedSeqs(page, "[data-testid=trace-lens-row]")).toEqual(A_S1_SEQS);
  // The lenses are routes of one page: the selection survived with no reload.
  expect(await page.evaluate(() => (window as unknown as { __kept?: boolean }).__kept)).toBe(true);
  expect(problems).toEqual([]);
});

test("FR_WLD_06 selecting an agent highlights it in all three lenses in <= 200 ms", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}/story${FAST}`);
  await expect(page.locator("[data-testid=story-lens] li[data-seq]")).toHaveCount(44, {
    timeout: 15_000,
  });
  // From Story: the Story rows and the World roster in the rail light up together.
  const fromStory = await msUntil(
    page,
    () =>
      page.getByTestId("story-lens").getByRole("button", { name: "Specialist 1" }).first().click(),
    [
      '[data-testid=story-lens] li[data-selected="true"]',
      '[data-testid=world-hud] button[aria-pressed="true"]',
      '[data-testid=selection-bar][data-selected-id="A_s1"]',
    ],
  );
  expect(fromStory, "Story to Story, World roster and bar").toBeLessThanOrEqual(200);
  // To Trace and to World: the highlight is there when the lens opens, within the same budget.
  const toTrace = await msUntil(page, () => lens(page, "Trace").click(), [
    '[data-testid=trace-lens-row][data-selected="true"]',
  ]);
  expect(toTrace, "Trace").toBeLessThanOrEqual(200);
  const toWorld = await msUntil(page, () => lens(page, "World").click(), [
    '[data-testid=world-hud] button[aria-pressed="true"]',
  ]);
  expect(toWorld, "World").toBeLessThanOrEqual(200);
  // And the other way: from Trace the World roster lights up at once.
  await lens(page, "Trace").click();
  await page.getByTestId("selection-bar").getByRole("button", { name: "Clear" }).click();
  const fromTrace = await msUntil(
    page,
    () => page.getByTestId("trace-lens").getByRole("button", { name: "A_s1" }).first().click(),
    [
      '[data-testid=trace-lens-row][data-selected="true"]',
      '[data-testid=world-hud] button[aria-pressed="true"]',
    ],
  );
  expect(fromTrace, "Trace to Trace and World roster").toBeLessThanOrEqual(200);
});

test("FR_WLD_06 the stage rings the selection without moving or replaying anything", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}?fixture=village-basic&seq=44&speed=100`);
  const frame = page.getByTestId("stage-frame");
  await expect(frame).toHaveAttribute("data-seq", "44");
  await finished(page);
  const snapshot = () => frame.locator("canvas").evaluate((c: HTMLCanvasElement) => c.toDataURL());
  const plain = await snapshot();
  await expect(frame).not.toHaveAttribute("data-selected", /.+/);

  const ms = await msUntil(page, () => hudRow(page, /Specialist 1/).click(), [
    '[data-testid=stage-frame][data-selected="A_s1"]',
  ]);
  expect(ms, "stage").toBeLessThanOrEqual(200);
  await expect.poll(snapshot).not.toBe(plain);
  await hudRow(page, /Mail Room/).click(); // a building is ringed too
  await expect(frame).toHaveAttribute("data-selected", "B1");
  await expect.poll(snapshot).not.toBe(plain);
  await page.getByTestId("selection-bar").getByRole("button", { name: "Clear" }).click();
  await expect(frame).not.toHaveAttribute("data-selected", /.+/);
  await expect.poll(snapshot).toBe(plain); // the ring is the only thing that was added
  await expect(frame).toHaveAttribute("data-seq", "44"); // selecting records and replays nothing
  expect(problems).toEqual([]);
});

test("FR_WLD_06 selection works from the keyboard and Clear undoes it", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize(DESKTOP);
  await page.goto(`${W}${FAST}`);
  await finished(page);
  await hudRow(page, /Specialist 2/).focus();
  await page.keyboard.press("Enter");
  await expect(hudRow(page, /Specialist 2/)).toHaveAttribute("aria-pressed", "true");
  await hudRow(page, /Verifier/).focus();
  await page.keyboard.press("Space");
  await expect(hudRow(page, /Verifier/)).toHaveAttribute("aria-pressed", "true");
  await expect(hudRow(page, /Specialist 2/)).toHaveAttribute("aria-pressed", "false"); // one at a time
  const clear = page.getByTestId("selection-bar").getByRole("button", { name: "Clear" });
  await clear.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("selection-bar")).toContainText("Choose anything to inspect it");
  await expect(page.locator('[aria-pressed="true"]')).toHaveCount(0);
  // Every control is at least 24 x 24 px.
  for (const control of await page.getByTestId("world-hud").getByRole("button").all()) {
    const b = await control.boundingBox();
    expect(b?.height ?? 0).toBeGreaterThanOrEqual(24);
    expect(b?.width ?? 0).toBeGreaterThanOrEqual(24);
  }
});

test("FR_WLD_06 Inspect opens from the selection for every kind of object", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  const kinds: Array<[string, string, string]> = [
    ["A_s1", "Specialist 1", "Agent"],
    ["B1", "Mail Room", "Common building"],
    ["L1", "Inbox", "Level"],
    ["D1", "Mail", "District"],
    ["I1", "Gmail", "Island"],
    ["art_triage_list", "Triage list", "Artifact"],
  ];
  for (const [id, name, kind] of kinds) {
    await page.goto(`${W}/inspect/${id}${FAST}`);
    await expect(page.getByTestId("inspect-panel"), id).toContainText(kind, { timeout: 15_000 });
    await expect(page.getByRole("heading", { level: 1 }), id).not.toHaveText("Not found");
    await expect(page.getByRole("heading", { level: 1 }), id).toContainText(name);
    // Inspecting an object selects it, so the way back to the world shows it ringed.
    await expect(page.getByTestId("selection-bar")).toHaveAttribute("data-selected-id", id);
  }
  await page.goto(`${W}/inspect/art_nope${FAST}`);
  await expect(page.getByRole("heading", { level: 1, name: "Not found" })).toBeVisible();
  await expect(page.getByTestId("selection-bar")).toContainText("Choose anything to inspect it");
  // From the bar on a lens, Inspect opens the selected object.
  await page.goto(`${W}/story${FAST}`);
  await page.getByTestId("story-lens").getByRole("button", { name: "Director" }).first().click();
  await page.getByTestId("selection-bar").getByRole("link", { name: "Inspect" }).click();
  await expect(page).toHaveURL(`${W}/inspect/A_dir`);
  await expect(page.getByRole("heading", { level: 1, name: "Director" })).toBeVisible();
  expect(problems).toEqual([]);
});

test("FR_WLD_06 selecting shifts nothing on the page and passes axe", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize(DESKTOP);
  for (const path of [`${W}/story${FAST}`, `${W}/trace${FAST}`, `${W}${FAST}`]) {
    await page.goto(path);
    await finished(page);
    const tops = () =>
      page
        .locator(
          "[data-testid=selection-bar], [data-testid=world-hud] .row, .story-list li, .trace-rows li",
        )
        .evaluateAll((els) => els.slice(0, 40).map((el) => el.getBoundingClientRect().top));
    // The rail scrolls: a row below the fold is brought into view first, so the click itself
    // scrolls nothing and only a selection's own shift would show.
    await hudRow(page, /Specialist 1/).scrollIntoViewIfNeeded();
    const before = await tops();
    await hudRow(page, /Specialist 1/).click();
    await expect(page.getByTestId("selection-bar")).toHaveAttribute("data-selected-id", "A_s1");
    expect(await tops(), path).toEqual(before);
    const axe = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag22aa"])
      .analyze();
    expect(axe.violations, path).toEqual([]);
  }
});

test("FR_WLD_06 on a phone every selection control is at least 44 x 44 px and nothing scrolls sideways", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize(MOBILE);
  for (const lensPath of ["/story", "/trace"]) {
    await page.goto(`${W}${lensPath}${FAST}`);
    await expect(page.locator("[data-seq]")).toHaveCount(44, { timeout: 15_000 });
    await page.locator("main [data-lens-control]").first().click();
    await expect(page.getByTestId("selection-bar")).toHaveAttribute("data-selected-id", /.+/);
    for (const control of await page.locator("main [data-lens-control]").all()) {
      const b = await control.boundingBox();
      expect(b?.height ?? 0, lensPath).toBeGreaterThanOrEqual(44);
      expect(b?.width ?? 0, lensPath).toBeGreaterThanOrEqual(44);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      MOBILE.width,
    );
  }
});
