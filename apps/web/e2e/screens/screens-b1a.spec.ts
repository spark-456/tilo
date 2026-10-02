// AGW-08 group B1a smoke: S-13..S-16 on the fixture client (PRD 18.3). Each test name carries the
// screen id. Helpers are in e2e/support/screens-b.ts.
import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { noLayoutShift, soon, visit } from "../support/screens-b";

test("S_13 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await visit(page, "/library", "Library and Memory Vault", async () => {
    await expect(page.getByTestId("library")).toContainText("Triage list");
    await expect(page.getByText("Memory reuses")).toBeVisible();
    await expect(page.getByTestId("memory-empty")).toBeVisible();
    await soon(page, "Search the library");
  });
  await page.getByRole("link", { name: "Version history" }).click();
  await expect(page).toHaveURL(/\/library\/artifacts$/);
  expect(problems).toEqual([]);
});

test("S_14 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await visit(page, "/worlds", "Worlds list and replays", async () => {
    const card = page.getByTestId("world-card");
    await expect(card).toContainText("Triage my inbox and answer the supplier about Thursday");
    await expect(card).toContainText("Replay of run #village_basic_1 recorded 29 Sep 2026"); // HR-4
    await expect(card).toContainText("Finished", { timeout: 15_000 });
    // The one primary action is in the first viewport at both sizes.
    const box = await page.locator("button.primary").boundingBox();
    expect((box?.y ?? 9999) + (box?.height ?? 0)).toBeLessThanOrEqual(
      page.viewportSize()?.height ?? 0,
    );
  });
  await page.getByRole("link", { name: "Open world" }).click();
  await expect(page).toHaveURL(/\/world\/w_village_basic$/);
  await page.goto("/worlds");
  await page.locator("button.primary").click();
  await expect(page.getByRole("heading", { level: 1, name: "Start" })).toBeVisible();
  expect(problems).toEqual([]);
});

test("S_15 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await visit(page, "/autonomy", "Autonomy", async () => {
    await expect(page.getByTestId("gates")).toContainText("Waits for you");
    // Every recorded authorisation (4 in the run) is listed with who gave it.
    const rows = page.getByTestId("autonomy-log").locator("li");
    await expect(rows).toHaveCount(4, { timeout: 15_000 });
    await expect(rows.last()).toContainText("Authorised by you");
    await soon(page, "Stop all autopilot");
    await expect(page.getByRole("button", { name: "Undo" }).first()).toHaveAttribute(
      "aria-disabled",
      "true",
    );
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
