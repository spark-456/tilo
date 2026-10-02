// AGW-08 group B2 smoke: S-21..S-24 on the fixture client (PRD 18.3). Each test name carries the
// screen id. Helpers are in e2e/support/screens-b.ts.
import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { noLayoutShift, soon, visit } from "../support/screens-b";

test("S_21 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await visit(page, "/library/artifacts", "Artifact history", async () => {
    // Four artifact events in the run, each with its recorded reason.
    const rows = page.getByTestId("artifact-rows").locator("li");
    await expect(rows).toHaveCount(4, { timeout: 15_000 });
    await expect(rows.first()).toContainText("Triage list, version 1");
    await expect(rows.first()).toContainText("Because:");
    await expect(page.getByRole("button", { name: /^Restore/ })).toHaveCount(4); // every version
    await soon(page, "Restore");
  });
  await page.getByRole("link", { name: "Why is this here?" }).first().click();
  await expect(page).toHaveURL(/\/world\/w_village_basic\/trace$/);
  expect(problems).toEqual([]);
});

test("S_22 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await visit(page, "/settings", "Settings", async () => {
    await expect(page.getByText("Removed from every store within 30 days")).toBeVisible();
    await soon(page, "Use Professional");
    await soon(page, "Export");
    await soon(page, "Delete");
    await soon(page, "Review Gmail access");
  });
  expect(problems).toEqual([]);
});

test("S_23 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await visit(page, "/estimate", "How we estimate", async () => {
    await expect(page.getByText("We count the units of work the agents finished")).toBeVisible();
    await expect(page.getByTestId("estimate-example")).toContainText(
      "About 8 to 18 min saved (estimate) for 13 credits.",
      { timeout: 15_000 },
    );
    await expect(page.getByTestId("status-rows")).toContainText("No live service is connected");
  });
  // Every estimate links here: the delivery screen's link lands on this screen.
  await page.goto("/world/w_village_basic/delivery?speed=100"); // the link shows once the run is finished (S-12)
  await page.getByRole("link", { name: "How we estimate" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "How we estimate" })).toBeVisible();
  expect(problems).toEqual([]);
});

test("S_24 renders, no console errors, placeholders aria-disabled", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  await visit(page, "/pilot", "Pilot diary", async () => {
    const field = page.getByLabel("What did Tilo do for you today?");
    await expect(field).toHaveAttribute("aria-disabled", "true");
    await expect(field).toHaveAttribute("title", "Coming soon");
    await expect(field).toHaveJSProperty("readOnly", true);
    const box = await field.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44); // the read-only field is a full-size target
    await soon(page, "Save today's diary");
    await soon(page, "Send the survey");
  });
  expect(problems).toEqual([]);
});

// UX-1: with a slow client and events arriving, nothing on S-21..S-24 moves.
noLayoutShift([
  ["S_21", "/library/artifacts", "Because:"],
  ["S_22", "/settings", "Removed from every store within 30 days"],
  ["S_23", "/estimate", "About 8 to 18 min saved"],
  ["S_24", "/pilot", "Results are aggregated"],
]);
