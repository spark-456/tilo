// UI-10 B8: a real run's World page against the LIVE Api (the fake tilo-api serves the recorded village-basic stream
// on GET /worlds/{id}/events, as many rows as /__control says). Nothing on the page is drawn before an event is
// recorded: with none the stage links are off with the reason; as events arrive the card fills in and the stage opens.
// Local only: `TILO_LIVE=1 pnpm exec playwright test e2e/live/run-progress.spec.ts --project=live --workers=1`.
import { type Page, expect, test } from "@playwright/test";

const API = `http://127.0.0.1:${process.env.TILO_LIVE_API_PORT ?? 5398}`;
const control = async (page: Page, body: Record<string, unknown>) =>
  expect((await page.request.post(`${API}/__control`, { data: body })).ok()).toBe(true);

test.beforeEach(async ({ page }) => {
  await control(page, { reset: true });
});

test("UI_10_B8_e2e_the_live_run_card_follows_the_recorded_events_and_gates_the_stage", async ({
  page,
}) => {
  await page.goto("/world/w_here");
  const card = page.locator('section[aria-label="Live run"]');
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card).toContainText("No recorded events yet");
  const stage = page.locator("a.park-world-live");
  // only a City has "Open live view" (as at the end of this test); when the link is there, no event means it is off
  if ((await stage.count()) > 0) {
    await expect(stage).toHaveAttribute("aria-disabled", "true");
    await expect(stage).not.toHaveAttribute("href", /.+/);
  }

  await control(page, { events: 12 });
  await expect(card).toContainText("12 recorded events", { timeout: 15_000 });
  await expect(card).toContainText("Working");
  await expect(card).not.toContainText("Done");
  // only a City has "Open live view"; the stage link, when the world is one, is a real link once events exist
  if ((await stage.count()) > 0) await expect(stage).toHaveAttribute("href", /\/stage$/);

  await control(page, { events: 44 });
  await expect(card).toContainText("44 recorded events", { timeout: 15_000 });
  await expect(card).toContainText("Done");
});
