// WIRE-3 (S-06 cards feed; FR-HIL-01, FR-HIL-02, FR-HIL-11; HR-1..HR-7): the Park decisions flow against the LIVE
// Api in a real browser. The page is /park/worlds ("Waiting for you"), served by a Vite with VITE_TILO_API_URL set
// and answered by a fake tilo-api (e2e/support/fakeCardsApi.mjs) that these tests steer through /__control:
// hold the reply, release it, refuse another world's card (what tilo-api does today), or say "already answered".
// Local only (TILO_LIVE=1): `TILO_LIVE=1 pnpm exec playwright test e2e/live --project=live --workers=1`.
import { type Locator, type Page, expect, test } from "@playwright/test";

const API = `http://127.0.0.1:${process.env.TILO_LIVE_API_PORT ?? 5398}`;

interface Logged {
  method: string;
  path: string;
  body?: { option?: string };
}

async function control(page: Page, body: Record<string, unknown>) {
  const r = await page.request.post(`${API}/__control`, { data: body });
  expect(r.ok()).toBe(true);
}
const log = async (page: Page): Promise<Logged[]> =>
  (await page.request.get(`${API}/__log`)).json() as Promise<Logged[]>;
const posts = async (page: Page) => (await log(page)).filter((e) => e.method === "POST");

test.beforeEach(async ({ page }) => {
  await control(page, { reset: true });
});

const waiting = (page: Page) => page.locator(".park-worlds-dec");
const card = (page: Page, title: string) => waiting(page).filter({ hasText: title });
const toast = (page: Page) => page.getByRole("status");
// `toHaveCount(0)` retries until it holds, and a toast hides itself after 4.2 s, so a "not shown" check that
// retried would pass once the toast was gone. This one reads the count once, at the moment it is asked.
const none = async (loc: Locator) => expect(await loc.count()).toBe(0);

async function openWorlds(page: Page) {
  await page.goto("/park/worlds");
  await expect(page.getByRole("heading", { name: "Worlds", level: 1 })).toBeVisible();
  await expect(card(page, "Pick a supplier shortlist")).toBeVisible({ timeout: 30_000 });
}

test("WIRE_3_e2e_the_live_queue_shows_the_served_cards_and_a_read_never_answers", async ({
  page,
}) => {
  await openWorlds(page);
  await expect(waiting(page)).toHaveCount(2);
  await expect(card(page, "Pick a supplier shortlist")).toContainText(
    "The brief cannot go out without a shortlist.",
  );
  // the tap's label is the suggested option of the served card, never a sample string
  await expect(
    card(page, "Pick a supplier shortlist").getByRole("button", { name: "Go on" }),
  ).toBeVisible();
  await expect(
    card(page, "Confirm the launch date").getByRole("button", { name: "Confirm" }),
  ).toBeVisible();
  const seen = await log(page);
  expect(seen.some((e) => e.method === "GET" && e.path.startsWith("/cards"))).toBe(true);
  expect(
    seen.filter((e) => e.method === "POST"),
    "reading answers nothing",
  ).toEqual([]);
});

test("WIRE_3_e2e_a_tap_is_recorded_only_after_the_reply_and_there_is_no_Undo", async ({ page }) => {
  await openWorlds(page);
  await control(page, { hold: true });
  const mine = card(page, "Pick a supplier shortlist");
  await mine.getByRole("button", { name: "Go on" }).click();

  // The POST is out, the reply is held: nothing is recorded yet (HR-1).
  await expect.poll(async () => (await posts(page)).length).toBe(1);
  await page.waitForTimeout(400);
  await none(page.getByText(/recorded/));
  await expect(mine.getByRole("button", { name: "Go on" })).toBeVisible();

  await control(page, { hold: false });
  await page.request.post(`${API}/__release`);

  // Now (and only now) the answer is recorded: the toast says what was recorded, with no Undo, and the card is done.
  await expect(toast(page)).toContainText("Go on recorded: Pick a supplier shortlist");
  await none(page.getByRole("button", { name: "Undo" }));
  await expect(mine.getByRole("button", { name: "Go on" })).toHaveCount(0);

  const sent = await posts(page);
  expect(sent, "exactly one POST per tap").toHaveLength(1);
  expect(sent[0]?.path).toBe("/worlds/w_here/cards/01000000000000000000000001/answer");
  expect(sent[0]?.body).toEqual({ option: "go_on" });
});

test("WIRE_3_e2e_another_worlds_card_is_refused_and_the_toast_offers_Open_in_world", async ({
  page,
}) => {
  await openWorlds(page);
  await control(page, { mode: "other_world" });
  const other = card(page, "Confirm the launch date");
  await other.getByRole("button", { name: "Confirm" }).click();

  await expect(toast(page).getByRole("button", { name: "Open in world" })).toBeVisible();
  await none(page.getByText(/recorded/));
  await expect(other.getByRole("button", { name: "Confirm" }), "the card stays open").toBeVisible();
  expect(await posts(page), "no retry").toHaveLength(1);

  await toast(page).getByRole("button", { name: "Open in world" }).click();
  await expect(page).toHaveURL(/\/park\/world\/w_other$/);
});

test("WIRE_3_e2e_a_rejected_answer_says_why_leaves_the_card_open_and_sends_one_POST", async ({
  page,
}) => {
  await openWorlds(page);
  await control(page, { mode: "already" });
  const mine = card(page, "Pick a supplier shortlist");
  await mine.getByRole("button", { name: "Go on" }).click();

  await expect(toast(page)).toContainText("This card was already answered.");
  await none(page.getByText(/recorded/));
  await expect(mine.getByRole("button", { name: "Go on" })).toBeVisible();
  await none(toast(page).getByRole("button", { name: "Open in world" }));
  expect(await posts(page), "no retry, no second answer").toHaveLength(1);
});

test("WIRE_3_e2e_the_Open_in_world_button_of_a_card_navigates_without_answering", async ({
  page,
}) => {
  await openWorlds(page);
  await card(page, "Confirm the launch date")
    .getByRole("button", { name: "Open in world" })
    .click();
  await expect(page).toHaveURL(/\/park\/world\/w_other$/);
  expect(await posts(page), "navigating never answers a card").toEqual([]);
});
