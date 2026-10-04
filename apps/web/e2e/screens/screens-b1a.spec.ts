// AGW-08 group B1a smoke: S-13..S-16 on the fixture client (PRD 18.3). Each test name carries the
// screen id. Helpers are in e2e/support/screens-b.ts.
import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { noLayoutShift, soon, visit } from "../support/screens-b";
import { DESKTOP } from "../support/viewports";

test("S_13 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await visit(page, "/library", "Library", async () => {
    await expect(page.getByTestId("library-rows")).toContainText("Triage list", {
      timeout: 15_000,
    });
    await expect(page.getByText("Deliverables", { exact: true }).first()).toBeVisible();
    await expect(page.getByTestId("memory-empty")).toBeVisible();
    await soon(page, "Search the library");
  });
  await page.getByRole("link", { name: "Version history" }).click();
  await expect(page).toHaveURL(/\/library\/artifacts$/);
  expect(problems).toEqual([]);
});

test("S_13 lists a deliverable only once artifact.delivered is recorded (HR-1)", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/library"); // recorded pace: artifact.delivered is about two minutes in
  await expect(page.getByTestId("library-empty")).toContainText("Nothing delivered yet");
  await expect(page.getByTestId("library-rows")).toHaveCount(0);
});

test("S_14 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await visit(page, "/worlds", "Worlds", async () => {
    const card = page.getByTestId("world-card");
    await expect(card).toContainText("Triage my inbox and answer the supplier about Thursday");
    await expect(card).toContainText("Replay of run #village_basic_1 recorded 29 Sep 2026"); // HR-4
    await expect(card).toContainText("Village · 1 level");
    await expect(card).toContainText("Finished", { timeout: 15_000 });
    await expect(card).toContainText("13 of 40 credits used");
    await expect(card.getByRole("progressbar")).toHaveAttribute("value", "1"); // finished is full
    // The one primary action is in the first viewport at both sizes.
    const box = await page.locator("button.primary").boundingBox();
    expect((box?.y ?? 9999) + (box?.height ?? 0)).toBeLessThanOrEqual(
      page.viewportSize()?.height ?? 0,
    );
  });
  await expect(page.getByRole("link", { name: "Open world" })).toHaveAttribute(
    "href",
    "/world/w_village_basic",
  );
  await page.locator("button.primary").click();
  await expect(page.getByRole("heading", { level: 1, name: "Start" })).toBeVisible();
  expect(problems).toEqual([]);
});

test("S_14 says Replaying, with no finished level, until world.completed is recorded", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/worlds?client_delay_ms=300");
  const card = page.getByTestId("world-card");
  await expect(card).toContainText("Replaying");
  await expect(card).not.toContainText("Finished");
  await expect(card).toContainText("0 of 1 level finished");
});

test("S_15 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await visit(page, "/autonomy", "Autonomy", async () => {
    await expect(page.getByTestId("gates")).toContainText("Waits for you");
    // Every recorded authorisation (4 in the run) is listed with who gave it, when, and a link.
    const rows = page.getByTestId("autonomy-log").locator("li");
    await expect(rows).toHaveCount(4, { timeout: 15_000 });
    await expect(rows.last()).toContainText("Authorised by you · 29 Sep 2026, 09:32 UTC");
    await expect(rows.last().getByRole("link")).toHaveAttribute("href", /\/trace$/);
    // Undo and report apply only to outgoing actions: one row in this run.
    await expect(page.getByRole("button", { name: /^Undo/ })).toHaveCount(1);
    await soon(page, "Stop all autopilot");
    await soon(page, "New rule");
  });
  expect(problems).toEqual([]);
});

test("S_16 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await visit(page, "/channels", "Channels", async () => {
    await expect(page.getByTestId("channel-islands")).toContainText("Connected");
    await expect(page.getByText("Your WhatsApp answer arrived.")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("STOP AUTOPILOT")).toBeVisible();
    await expect(page.getByText(/Whatsapp/)).toHaveCount(0);
    await soon(page, "Bind a WhatsApp number");
  });
  expect(problems).toEqual([]);
});

// UX-1: with a slow client and events arriving, nothing on S-13..S-16 moves.
noLayoutShift([
  ["S_13", "/library", "Triage list"],
  ["S_14", "/worlds", "Replay of run #village_basic_1"],
  ["S_15", "/autonomy", "Authorised by you"],
  ["S_16", "/channels", "Your WhatsApp answer arrived."],
]);
