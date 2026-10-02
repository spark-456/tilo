import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "../support/viewports";

const pdf = (name: string) => ({
  name,
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4 fixture"),
});

function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warning") errors.push(msg.text());
  });
  return errors;
}

for (const viewport of [DESKTOP, MOBILE]) {
  const size = `${viewport.width}x${viewport.height}`;

  test(`PRD-18.3 S_01: one primary button in the first viewport; a suggested task fills the box without submitting at ${size}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const errors = watchConsole(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1, name: "Start" })).toBeVisible();
    await expect(page.locator("button.primary")).toHaveCount(1);
    const start = page.getByRole("button", { name: "Start", exact: true });
    await expect(start).toBeDisabled(); // an empty box has nothing to start
    const box = await start.boundingBox();
    expect(box && box.y + box.height <= viewport.height).toBe(true);
    expect(box && box.width >= 44 && box.height >= (viewport.width < 768 ? 44 : 24)).toBe(true);

    const chips = page.getByRole("group", { name: "Suggested tasks" }).getByRole("button");
    await expect(chips).toHaveCount(3);
    const first = (await chips.first().textContent()) ?? "";
    await chips.first().click();
    await expect(page.getByLabel("Describe your task")).toHaveValue(first);
    await expect(start).toBeEnabled();
    expect(new URL(page.url()).pathname).toBe("/");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(results.violations).toEqual([]);
    expect(errors).toEqual([]);
  });

  test(`FR-INT-01 S_01: text plus 3 files submits once and lands on Understanding at ${size}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const errors = watchConsole(page);
    let intakeRequests = 0;
    page.on("request", (r) => {
      if (r.url().includes("/intake")) intakeRequests++;
    });
    await page.goto("/");
    await page.getByLabel("Describe your task").fill("Compare the three supplier quotes");
    await page
      .locator('input[type="file"]')
      .setInputFiles([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")]);
    await expect(
      page.getByRole("list", { name: "Attached files" }).getByRole("listitem"),
    ).toHaveCount(3);
    await page.getByRole("button", { name: "Start", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Understanding" })).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/task/task_fixture_1/understanding");
    expect(intakeRequests).toBe(0); // the fixture client never touches the network
    expect(errors).toEqual([]);
  });

  test(`FR-INT-01 S_01: an 11th file shows the server's wording and blocks Start at ${size}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await page.getByLabel("Describe your task").fill("task");
    const eleven = Array.from({ length: 11 }, (_, i) => pdf(`f${i}.pdf`));
    await page.locator('input[type="file"]').setInputFiles(eleven);
    await expect(page.getByRole("alert").first()).toHaveText("11 files attached; the limit is 10.");
    await expect(page.getByRole("button", { name: "Start", exact: true })).toBeDisabled();
  });

  // UX-1: the reserved box. Warm the dev server first so a cold compile cannot add a late shift.
  test(`PRD-18.3 S_01 UX_1: zero layout shifts while a slow client answers at ${size}`, async ({
    page,
  }) => {
    test.setTimeout(60_000);
    await page.setViewportSize(viewport);
    await page.goto("/");
    await page.addInitScript(() => {
      const w = window as unknown as { __shifts: number[] };
      w.__shifts = [];
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries())
          w.__shifts.push((entry as unknown as { value: number }).value);
      }).observe({ type: "layout-shift", buffered: true });
    });
    await page.goto("/?client_delay_ms=3000");
    await page.getByLabel("Describe your task").fill("Compare the three supplier quotes");
    await page.locator('input[type="file"]').setInputFiles([pdf("a.pdf")]);
    await page.getByRole("button", { name: "Start", exact: true }).click();
    await expect(page.getByRole("button", { name: /^Start…/ })).toHaveAttribute(
      "aria-busy",
      "true",
    );
    await expect(page.getByRole("heading", { level: 1, name: "Understanding" })).toBeVisible({
      timeout: 20_000,
    });
    await page.waitForTimeout(300); // let a late shift be reported
    const shifts = await page.evaluate(
      () => (window as unknown as { __shifts: number[] }).__shifts,
    );
    expect(shifts).toEqual([]);
  });
}
