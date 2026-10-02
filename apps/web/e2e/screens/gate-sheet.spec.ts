// AGW-05 smoke: S-07 gate sheet on the fixture client, and the card fixtures at both viewports
// (PRD 18.3, 18.4, FR-CHN-01). The village replay asks for the gate at seq 34 and has a person
// answer it at seq 37, so `?speed=5` shows no gate for about 17 s, a waiting gate for about 9 s,
// then a gate a person opened. The replay does not carry the card for that gate, so the sheet says
// so and offers no answer; the six contract cards are drawn on the dev gallery instead.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { expectTypeScale } from "../support/screens-b";
import { DESKTOP, MOBILE } from "../support/viewports";

const SUMMARY = "The reply is ready. Sending it needs your approval.";
const noIds = /\b[A-Z]_[a-z0-9]+\b|\bG\d\b|\b[a-z]+_[a-z0-9_]+\b/;

for (const viewport of [DESKTOP, MOBILE]) {
  const at = `${viewport.width}x${viewport.height}`;

  test(`S_07 follows the gate's events and opens only when a person's answer is recorded at ${at}`, async ({
    page,
  }) => {
    test.setTimeout(90_000);
    const problems = watchConsole(page);
    await page.setViewportSize(viewport);
    await page.goto("/needs-you/gate?speed=5", { waitUntil: "commit" }); // replay starts at mount
    await expect(page.getByRole("heading", { level: 1, name: "Approval gate" })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByTestId("gate-empty")).toBeVisible(); // no gate before seq 34 (HR-1)

    const sheet = page.getByTestId("gate-sheet");
    await expect(sheet).toHaveAttribute("data-gate-state", "waiting", { timeout: 30_000 });
    await expect(sheet).toContainText(SUMMARY);
    await expect(sheet).toContainText("Send email"); // the exact action, from the recorded event
    await expect(sheet).toContainText("This replay did not record the recipient.");
    await expect(sheet).toContainText("Once sent, it can't be unsent.");
    await expect(sheet).toContainText("Reply draft, version 1");
    for (const label of ["Approve", "Edit first", "Hold"]) {
      const button = sheet.getByRole("button", { name: new RegExp(label) });
      await expect(button).toHaveAttribute("aria-disabled", "true"); // nothing sends without a card
      await expect(button).toHaveAttribute("title", "Coming soon");
    }
    await expect(sheet.getByTestId("policy-stamp")).toHaveCount(0);
    expect(await page.locator("main button.primary").count()).toBeLessThanOrEqual(1); // UX-1
    expect(await page.getByTestId("screen-page").innerText()).not.toMatch(noIds);
    await expectTypeScale(page);
    const axe = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag22aa"])
      .analyze();
    expect(axe.violations).toEqual([]);

    // approval.resolved (approve) is what opens the gate, and it links its authorisation (HR-7).
    await expect(sheet).toHaveAttribute("data-gate-state", "decided", { timeout: 30_000 });
    await expect(sheet).toHaveAttribute("data-opened-by", "person");
    await expect(sheet).toContainText("Opened. You approved this at 29 Sep 2026, 09:32 UTC.");
    await expect(sheet.getByTestId("policy-stamp")).toHaveCount(0);
    await sheet.getByRole("link", { name: "See authorisation" }).click();
    await expect(page).toHaveURL(/\/world\/w_village_basic\/trace$/);
    expect(problems).toEqual([]);
  });

  test(`S_06 links a waiting gate to its sheet at ${at}`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.setViewportSize(viewport);
    await page.goto("/needs-you?speed=5", { waitUntil: "commit" });
    await page.getByRole("link", { name: /^Review the gate/ }).click({ timeout: 30_000 });
    await expect(page).toHaveURL(/\/needs-you\/gate\?run=r_village_basic_1&gate=G1$/);
    await expect(page.getByRole("heading", { level: 1, name: "Approval gate" })).toBeVisible();
    await expect(page.getByTestId("gate-sheet")).toContainText(SUMMARY);
  });

  // UX-1: with a client that answers after 3 s and events arriving, nothing on S-07 moves.
  test(`S_07 UX_1 has zero layout shifts while a slow client answers at ${at}`, async ({
    page,
  }) => {
    test.setTimeout(90_000);
    await page.setViewportSize(viewport);
    await page.goto("/needs-you/gate?speed=100"); // warm the dev server
    await expect(page.getByRole("heading", { level: 1, name: "Approval gate" })).toBeVisible();
    await page.addInitScript(() => {
      const w = window as unknown as { __shifts: number[] };
      w.__shifts = [];
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries())
          w.__shifts.push((entry as unknown as { value: number }).value);
      }).observe({ type: "layout-shift", buffered: true });
    });
    await page.goto("/needs-you/gate?client_delay_ms=3000&speed=5", { waitUntil: "commit" });
    await expect(page.getByText("Loading the gate")).toBeVisible();
    const sheet = page.getByTestId("gate-sheet");
    await expect(sheet).toHaveAttribute("data-gate-state", "waiting", { timeout: 40_000 });
    await expect(sheet).toHaveAttribute("data-gate-state", "decided", { timeout: 40_000 });
    await page.waitForTimeout(300);
    const shifts = await page.evaluate(
      () => (window as unknown as { __shifts: number[] }).__shifts,
    );
    expect(shifts).toEqual([]);
  });
}

// FR-CHN-01: the same card shows the same fields at 1440x900 and 390x844 (dev gallery).
test("FR-CHN-01 S_06 the same card shows the same fields at 1440x900 and 390x844", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  const fields: string[][] = [];
  for (const viewport of [DESKTOP, MOBILE]) {
    await page.setViewportSize(viewport);
    await page.goto("/screens/cards");
    await expect(page.getByRole("heading", { level: 1, name: "Card fixtures" })).toBeVisible();
    const cards = page.locator(".need-card, .gate-sheet");
    await expect(cards).toHaveCount(9); // six fixtures, a person-opened and a policy-opened gate, one answerable
    fields.push(
      await cards.evaluateAll((els) =>
        els.map((el) => (el as HTMLElement).innerText.replace(/\s+/g, " ").trim()),
      ),
    );
    expect(await page.getByTestId("screen-page").innerText()).not.toMatch(noIds);
    const hero = page.locator("main button.primary"); // the one filled button: 48 px, 56 on a phone
    await expect(hero).toHaveCount(1);
    expect((await hero.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(
      viewport === MOBILE ? 56 : 48,
    );
    await expectTypeScale(page);
    // Targets: 24 px on desktop, 44 px on mobile (PRD 17.2). Enabled controls only.
    const min = viewport === MOBILE ? 44 : 24;
    const small = await page
      .locator("main a, main label.need-option, main button:not([aria-disabled=true])")
      .evaluateAll(
        (els, floor) =>
          els.flatMap((el) => {
            const box = el.getBoundingClientRect();
            return box.height < floor ? [`${el.textContent?.slice(0, 20)} ${box.height}`] : [];
          }),
        min,
      );
    expect(small).toEqual([]);
    const axe = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag22aa"])
      .analyze();
    expect(axe.violations).toEqual([]);
    // Heading order: no level is skipped (h1, h2 sections, h3 cards).
    const order = await new AxeBuilder({ page }).withRules(["heading-order"]).analyze();
    expect(order.violations).toEqual([]);
  }
  expect(fields[0]).toEqual(fields[1]);
  expect(fields[0]?.[2]).toContain("orders@example.com"); // the gate card names its recipient
  expect(problems).toEqual([]);
});

// The answerable gate on the dev gallery uses a stub client: Approve sends, no event follows, so
// the card says it is waiting and then that no confirmation was recorded, with the button usable.
test("S_07 an answer with no recorded confirmation says so and can be sent again", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize(DESKTOP);
  await page.goto("/screens/cards");
  const hero = page.locator("main button.primary");
  await hero.click();
  await expect(page.getByText("Waiting for confirmation…")).toBeVisible();
  await expect(hero).toBeDisabled();
  await expect(
    page.getByText("No confirmation has been recorded for your answer yet."),
  ).toBeVisible({ timeout: 15_000 });
  await expect(hero).toBeEnabled();
});

// A gate the address names but the run never recorded is "not recorded", never another gate.
test("S_07 an unknown gate says it is not recorded and shows no other gate", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/needs-you/gate?run=r_village_basic_1&gate=G999&speed=100", {
    waitUntil: "commit",
  });
  await expect(page.getByTestId("gate-not-found")).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(3000); // the whole replay plays: G1 is recorded, G999 never is
  await expect(page.getByTestId("gate-sheet")).toHaveCount(0);
  await expect(page.getByTestId("gate-not-found")).toBeVisible();
});
