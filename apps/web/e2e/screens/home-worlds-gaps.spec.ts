import { expect, test } from "@playwright/test";
import { readShifts, resetShifts, watchShifts } from "../support/shifts";
import { DESKTOP } from "../support/viewports";

// #227 desktop gaps, S-01 and S-14 (artboards "Tilo Home v2" and "Tilo Worlds"): the Home top line
// is a greeting, or the decisions the queue lists when some wait; the Worlds hero card shows the
// crew from the recorded run. Both read recorded events only (HR-1).

test("S-01 the top line is a greeting with nothing waiting, and never names a person", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/");
  const brief = page.getByTestId("home-brief");
  await expect(brief).toHaveAttribute("data-tone", "calm");
  await expect(brief).toHaveText(/^Good (morning|afternoon|evening)\.$/);
});

test("S-01 a waiting decision takes the top line, links to Needs you and moves nothing", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize(DESKTOP);
  await watchShifts(page);
  await page.goto("/needs-you?speed=5", { waitUntil: "commit" }); // the replay starts at mount
  await expect(page.getByTestId("needs-queue").locator("li")).toHaveCount(1, { timeout: 30_000 });
  await page
    .getByRole("navigation", { name: /primary/i })
    .getByRole("link", { name: /^Home/ })
    .click();
  const brief = page.getByTestId("home-brief");
  await expect(brief).toHaveAttribute("data-tone", "needs");
  await expect(brief).toContainText("1 decision is waiting in Triage my inbox");
  const before = await page.getByRole("heading", { level: 1 }).boundingBox();
  await resetShifts(page);
  await page.waitForTimeout(1500);
  expect(await readShifts(page)).toEqual([]);
  expect((await page.getByRole("heading", { level: 1 }).boundingBox())?.y).toBe(before?.y);
  await brief.getByRole("link", { name: "Review" }).click();
  await expect(page).toHaveURL(/\/needs-you/);
});

test("S-14 the hero card names every agent of the crew and who has joined", async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/worlds?speed=1000");
  const crew = page.getByTestId("crew");
  await expect(crew.locator("li")).toHaveCount(5);
  await expect(crew.locator("li[data-joined='true']")).toHaveCount(5, { timeout: 20_000 });
  await expect(page.locator(".world-eyebrow")).toHaveText("Finished");
});
