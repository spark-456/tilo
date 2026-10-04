import { type Page, expect, test } from "@playwright/test";
import { watchConsole } from "./support/screens";
import { DESKTOP } from "./support/viewports";
import {
  canvasColours,
  canvasSnapshot,
  fixtureUrl,
  stageCanvas,
  stageFrame,
  stageSeq,
} from "./support/world";

// Bundle B2 of #227 (PRD 9.4, 9.6, 18.3 S-04): /world/:id draws the run the active client serves,
// not only a ?fixture= replay. The client replays at 1x, so ?speed=1000 stands in for "wait out the
// run" and ?seq=N for "show the run as it stood at seq N" (HR-6, shown in the badge).

test.use({ viewport: DESKTOP });

const W = "/world/w_village_basic";
const plain = (seq: number) => `${W}?seq=${seq}&speed=1000`;

async function shot(page: Page, url: string, seq: number): Promise<string> {
  await page.goto(url);
  await expect.poll(() => stageSeq(page), { timeout: 20_000 }).toBe(seq);
  return canvasSnapshot(page);
}

test("FR-WLD-04 world route: /world/w_village_basic draws the run, not a bare iso grid", async ({
  page,
}) => {
  const problems = watchConsole(page);
  await page.goto("/");
  await expect(stageCanvas(page)).toBeVisible();
  const bare = await canvasColours(page);
  await page.goto(`${W}?speed=1000`);
  await expect.poll(() => stageSeq(page), { timeout: 20_000 }).toBe(44);
  expect(await canvasColours(page)).toBeGreaterThan(bare * 8);
  expect(problems).toEqual([]);
});

test("FR-WLD-04 world route: it draws exactly what the fixture replay draws at the same seq", async ({
  page,
}) => {
  for (const seq of [8, 23, 40]) {
    const fixture = await shot(page, fixtureUrl("village-basic", { seq }), seq);
    expect(await shot(page, plain(seq), seq), `seq ${seq}`).toBe(fixture);
  }
});

test("FR-WLD-04 world route: a building's state follows the recorded events", async ({ page }) => {
  const pictures = new Set<string>();
  for (const seq of [8, 21, 23, 40]) pictures.add(await shot(page, plain(seq), seq));
  expect(pictures.size, "planned, constructing, operational and completed look different").toBe(4);
  // A data transfer and a channel message are recorded and never drawn (HR-5).
  expect(await shot(page, plain(22), 22)).toBe(await shot(page, plain(21), 21));
});

test("HR-2 world route: once the run ends the canvas is pixel-identical for 3 s", async ({
  page,
}) => {
  await page.goto(`${W}?speed=1000`);
  await expect.poll(() => stageSeq(page), { timeout: 20_000 }).toBe(44);
  await page.waitForTimeout(2_500);
  const first = await canvasSnapshot(page);
  await page.waitForTimeout(3_000);
  expect(await canvasSnapshot(page)).toBe(first);
});

test("FR-WLD-04 world route: reduced motion ends on the same picture as jumping to the last seq", async ({
  browser,
}) => {
  const ctx = await browser.newContext({ viewport: DESKTOP, reducedMotion: "reduce" });
  const page = await ctx.newPage();
  const jumped = await shot(page, plain(44), 44);
  await page.goto(`${W}?speed=1000`);
  await expect.poll(() => stageSeq(page), { timeout: 20_000 }).toBe(44);
  await page.waitForTimeout(2_000);
  expect(await canvasSnapshot(page)).toBe(jumped);
  await ctx.close();
});

test("FR-WLD-06 world route: the stage rings the selection, and Clear takes the ring away", async ({
  page,
}) => {
  const problems = watchConsole(page);
  const frame = stageFrame(page);
  const bare = await shot(page, plain(44), 44);
  await page
    .getByTestId("world-hud")
    .getByRole("button", { name: /Specialist 1/ })
    .click();
  await expect(frame).toHaveAttribute("data-selected", "A_s1");
  await expect.poll(() => canvasSnapshot(page)).not.toBe(bare);
  await page
    .getByTestId("world-hud")
    .getByRole("button", { name: /Mail Room/ })
    .click();
  await expect(frame).toHaveAttribute("data-selected", "B1");
  await expect.poll(() => canvasSnapshot(page)).not.toBe(bare);
  await page.getByTestId("selection-bar").getByRole("button", { name: "Clear" }).click();
  await expect(frame).not.toHaveAttribute("data-selected", /.+/);
  await expect.poll(() => canvasSnapshot(page)).toBe(bare);
  expect(problems).toEqual([]);
});

test("PRD-18.3 world route: drawing the world shifts nothing in or around the stage", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const w = window as unknown as { __hits: string[] };
    w.__hits = [];
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        const shift = e as unknown as { hadRecentInput: boolean; sources?: { node?: Node }[] };
        for (const s of shift.sources ?? []) {
          const el = s.node instanceof Element ? s.node : s.node?.parentElement;
          if (el?.closest("[data-testid=stage-frame], .stage-frame, canvas")) {
            w.__hits.push(el.tagName);
          }
        }
      }
    }).observe({ type: "layout-shift", buffered: true });
  });
  await page.goto(`${W}?speed=1000`);
  await expect.poll(() => stageSeq(page), { timeout: 20_000 }).toBe(44);
  await page.waitForTimeout(1_000);
  expect(await page.evaluate(() => (window as unknown as { __hits: string[] }).__hits)).toEqual([]);
});
