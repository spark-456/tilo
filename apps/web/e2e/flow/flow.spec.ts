import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "../support/viewports";

const SCREENS = ["Start", "Understanding", "Approaches", "World", "Delivery"] as const;
const BANNER = "Fixture replay — dev data, not a real run";

/** Asserts what every flow screen must show: heading, banner, one filled primary button, axe. */
async function checkScreen(page: Page, heading: string) {
  await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  // HR-4, BQ-07: the fixture client is active, so the banner is on every screen.
  await expect(page.getByTestId("fixture-replay-banner")).toHaveText(BANNER);
  await expect(page.locator("button.primary")).toHaveCount(1); // UX-1
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(results.violations).toEqual([]);
}

for (const viewport of [DESKTOP, MOBILE]) {
  test(`PRD-18.3 flow: walks Start, Understanding, Approaches, World and Delivery on the fixture client at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    test.setTimeout(90_000); // five axe runs and a Pixi init, under a parallel suite
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error" || msg.type() === "warning") errors.push(msg.text());
    });

    await page.goto("/");
    for (const [i, screen] of SCREENS.entries()) {
      await checkScreen(page, screen);
      if (screen === "World") {
        await expect(page.getByTestId("stage-frame")).toHaveAttribute("data-stage-ready", "true");
      }
      const next = SCREENS[i + 1];
      if (!next) break;
      const primary = page.locator("button.primary");
      await expect(primary).toBeEnabled();
      await primary.click();
      await expect(page.getByRole("heading", { level: 1, name: next })).toBeVisible();
    }
    expect(page.url()).toMatch(/\/world\/w_village_basic\/delivery$/);
    expect(errors).toEqual([]);
  });
}

// UX-2 / PRD-18.1: the client answers after 400 ms (?client_delay_ms), so the busy state is
// observable. The latency is measured in the page from the click to the aria-busy mutation.
for (const viewport of [DESKTOP, MOBILE]) {
  test(`PRD-18.1 UX-2: the primary button of every flow screen shows busy feedback within 100 ms at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    test.setTimeout(60_000);
    await page.setViewportSize(viewport);
    await page.goto("/?client_delay_ms=400");
    for (const [i, screen] of SCREENS.entries()) {
      await expect(page.getByRole("heading", { level: 1, name: screen })).toBeVisible();
      await expect(page.locator("button.primary")).toBeEnabled();
      const ms = await page.evaluate(
        () =>
          new Promise<number>((resolve) => {
            const button = document.querySelector<HTMLButtonElement>("button.primary");
            if (!button) throw new Error("no primary button");
            const start = performance.now();
            const watch = new MutationObserver(() => {
              if (button.getAttribute("aria-busy") === "true") {
                watch.disconnect();
                resolve(performance.now() - start);
              }
            });
            watch.observe(button, { attributes: true, attributeFilter: ["aria-busy"] });
            button.click();
          }),
      );
      expect(ms, `${screen} busy feedback`).toBeLessThan(100);
      const next = SCREENS[i + 1] ?? "Start";
      await expect(page.getByRole("heading", { level: 1, name: next })).toBeVisible();
    }
  });
}
