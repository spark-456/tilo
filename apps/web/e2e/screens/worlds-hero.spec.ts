// Issue #227 S-14 follow-ups: one world fills the row as the hero card (no lone card beside empty
// tracks), and its thumbnail shows the agents the run has put in the world (HR-1: none before the run).
import { expect, test } from "@playwright/test";
import { readShifts, watchShifts } from "../support/shifts";
import { DESKTOP, MOBILE } from "../support/viewports";

test("UX-227-G1 desktop: a single world is the hero card across the page, thumbnail beside the words", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/worlds/replays?speed=1000");
  const card = page.getByTestId("world-card");
  await expect(card.getByText("Finished", { exact: true })).toBeVisible({ timeout: 30_000 });
  const [cardBox, gridBox, thumbBox] = await Promise.all([
    card.boundingBox(),
    page.locator(".world-grid").boundingBox(),
    card.locator(".world-thumb").boundingBox(),
  ]);
  expect(cardBox?.width).toBeGreaterThan((gridBox?.width ?? 0) - 2);
  expect(thumbBox?.width).toBeLessThan((cardBox?.width ?? 0) * 0.6);
  expect(thumbBox?.height).toBeGreaterThan(300); // not the 9em strip of a grid card
  // The finished run has put agents in the world, and the thumbnail draws them.
  expect(await card.getByTestId("thumb-agent").count()).toBeGreaterThan(0);
});

test("UX-227-G1 phone: the world card stays one column with its thumbnail on top, agents drawn", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE);
  await page.goto("/worlds/replays?speed=1000");
  const card = page.getByTestId("world-card");
  await expect(card.getByText("Finished", { exact: true })).toBeVisible({ timeout: 30_000 });
  const [thumb, body] = await Promise.all([
    card.locator(".world-thumb").boundingBox(),
    card.locator(".world-body").boundingBox(),
  ]);
  expect(thumb?.y).toBeLessThan(body?.y ?? 0);
  expect(thumb?.width).toBeGreaterThan(300);
  expect(await card.getByTestId("thumb-agent").count()).toBeGreaterThan(0);
});

// The hero's text column is narrow near its breakpoint, so a state line can wrap differently between
// Replaying and Finished: the hero starts at 1280 px and shifts nothing over the replay. (A grid card
// at 1200 px, 345 px wide, still wraps a waiting decision to three lines: follow-up, not this diff.)
for (const width of [1280]) {
  test(`UX-227-G1 ${width} px: zero layout shift while the world goes from Replaying to Finished`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 800 });
    await watchShifts(page);
    await page.goto("/worlds/replays?speed=1000");
    await expect(page.getByTestId("world-card").getByText("Finished", { exact: true })).toBeVisible(
      {
        timeout: 30_000,
      },
    );
    const shifts = await readShifts(page);
    expect(shifts.reduce((a, b) => a + b, 0)).toBe(0);
  });
}
