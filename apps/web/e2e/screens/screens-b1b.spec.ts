// AGW-08 group B1b smoke: S-17..S-19 on the fixture client (PRD 18.3). Each test name carries the
// screen id. Helpers are in e2e/support/screens-b.ts.
import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { noLayoutShift, soon, visit } from "../support/screens-b";
import { DESKTOP } from "../support/viewports";

test("S_17 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await visit(page, "/mail", "Email Autopilot home", async () => {
    await expect(
      page.getByText("The reply went to the supplier in the same thread.").first(),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("12 new emails came over from Gmail.")).toBeVisible();
    await expect(page.getByTestId("time-saved")).toContainText(
      "About 8 to 18 min saved (estimate)",
    );
    await soon(page, "Edit my style profile");
  });
  await page.getByRole("link", { name: "How we estimate" }).click();
  await expect(page).toHaveURL(/\/estimate$/);
  expect(problems).toEqual([]);
});

test("S_18 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await visit(page, "/team", "Team Lead console", async () => {
    await expect(page.getByTestId("lead-queue")).toContainText(
      "Two quotes use different pack sizes.",
    );
    await expect(page.getByText("You approved sending the reply on WhatsApp.")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("lead-stats")).toContainText("No Team Lead has answered");
    await soon(page, "Promote an answer to a skill");
  });
  expect(problems).toEqual([]);
});

test("S_19 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await visit(page, "/connections", "Connections", async () => {
    const list = page.getByTestId("connection-list");
    await expect(list).toContainText("Gmail");
    await expect(list).toContainText("Send email needs a gate");
    await expect(page.getByTestId("consent-list")).toContainText("Google drive");
    await soon(page, "Disconnect Gmail");
  });
  await page.getByRole("link", { name: "Review" }).click();
  await expect(page).toHaveURL(/\/needs-you\/consent$/);
  expect(problems).toEqual([]);
});

test("S_19 shows one loading box, then the data, with a slow client", async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/connections?client_delay_ms=8000");
  await expect(page.getByText("Loading the connections…")).toBeVisible();
  await expect(page.getByTestId("connection-list")).toBeVisible({ timeout: 15_000 });
});

// UX-1: with a slow client and events arriving, nothing on S-17..S-19 moves.
noLayoutShift([
  ["S_17", "/mail", "About 8 to 18 min saved"],
  ["S_18", "/team", "You approved sending the reply on WhatsApp."],
  ["S_19", "/connections", "Send email needs a gate"],
]);
