// AGW-05 smoke: S-06 Needs-you queue on the fixture client (PRD 18.3, 10.2). The village replay
// asks for the gate at seq 34 and has it answered at seq 37, so `?speed=5` leaves the queue empty
// for about 17 s, one row for about 9 s, then empty again. Helpers are in e2e/support.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { expectTypeScale } from "../support/screens-b";
import { DESKTOP, MOBILE } from "../support/viewports";

const SUMMARY = "The reply is ready. Sending it needs your approval.";

// HR-6: both Needs-you screens replay the run at the client's speed, so both say so.
for (const path of ["/needs-you", "/needs-you/gate"]) {
  test(`S_06 S_07 HR-6 shows the speed badge at ?speed=8 on ${path}`, async ({ page }) => {
    await page.goto(`${path}?speed=8`);
    await expect(page.getByTestId("speed-badge")).toHaveText("8×");
  });
}

test("S_06 moves focus to the queue heading when the focused row closes", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize(DESKTOP);
  await page.goto("/needs-you?speed=5", { waitUntil: "commit" }); // the replay starts at mount, not at load
  const link = page.getByRole("link", { name: /^Review the gate/ });
  await link.waitFor({ timeout: 30_000 });
  await link.focus();
  await expect(page.getByTestId("needs-empty")).toBeVisible({ timeout: 30_000 }); // the row closed
  await expect(page.getByRole("heading", { level: 2, name: "Waiting for you" })).toBeFocused();
});

for (const viewport of [DESKTOP, MOBILE]) {
  test(`S_06 follows the run's events and shows the same row at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    test.setTimeout(90_000);
    const problems = watchConsole(page);
    await page.setViewportSize(viewport);
    await page.goto("/needs-you?speed=5", { waitUntil: "commit" }); // the replay starts at mount, not at load
    await expect(page.getByRole("heading", { level: 1, name: "Needs you" })).toBeVisible();
    await expect(page.getByTestId("fixture-replay-banner")).toBeVisible();
    // Before approval.requested nothing waits (HR-1): an honest empty state, no row.
    await expect(page.getByTestId("needs-empty")).toBeVisible();
    await expect(page.getByTestId("needs-queue")).toHaveCount(0);

    const rows = page.getByTestId("needs-queue").locator("li");
    await expect(rows).toHaveCount(1, { timeout: 30_000 });
    await expect(rows.first()).toContainText(SUMMARY);
    await expect(rows.first()).toContainText("Approval gate"); // the rung in words, not colour alone
    await expect(rows.first()).toContainText("Specialist 2 · Mail");
    await expect(rows.first()).toContainText("Send email · Cannot be undone");
    // The text carries no machine ids (people read names), and sizes sit on the PRD 18.2 scale.
    const text = await page.getByTestId("screen-page").innerText();
    expect(text).not.toMatch(/\b[A-Z]_[a-z0-9]+\b|\bG\d\b/);
    await expectTypeScale(page);
    expect(await page.locator("main button.primary").count()).toBeLessThanOrEqual(1); // UX-1
    if (viewport === DESKTOP) {
      await expect(page.getByTestId("rail-needs")).toContainText(SUMMARY); // the rail agrees
    }
    const axe = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag22aa"])
      .analyze();
    expect(axe.violations).toEqual([]);

    // approval.resolved closes the card.
    await expect(page.getByTestId("needs-empty")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("needs-queue")).toHaveCount(0);
    expect(problems).toEqual([]);
  });

  // UX-1: with a client that answers after 3 s and events arriving, nothing on S-06 moves.
  test(`S_06 UX_1 has zero layout shifts while a slow client answers at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    test.setTimeout(90_000);
    await page.setViewportSize(viewport);
    // Warm the dev server (dependency optimisation, fonts) so a cold start cannot show a reflow.
    await page.goto("/needs-you?speed=100");
    await expect(page.getByRole("heading", { level: 1, name: "Needs you" })).toBeVisible();
    await page.addInitScript(() => {
      const w = window as unknown as { __shifts: number[] };
      w.__shifts = [];
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries())
          w.__shifts.push((entry as unknown as { value: number }).value);
      }).observe({ type: "layout-shift", buffered: true });
    });
    await page.goto("/needs-you?client_delay_ms=3000&speed=5", { waitUntil: "commit" });
    await expect(page.getByText("Loading the cards")).toBeVisible();
    await expect(page.getByText(SUMMARY).first()).toBeVisible({ timeout: 40_000 }); // arrives
    await expect(page.getByTestId("needs-empty")).toBeVisible({ timeout: 40_000 }); // closes
    await page.waitForTimeout(300); // let a late shift be reported
    const shifts = await page.evaluate(
      () => (window as unknown as { __shifts: number[] }).__shifts,
    );
    expect(shifts).toEqual([]);
  });
}
