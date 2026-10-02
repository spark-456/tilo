import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "../support/viewports";

const SCREENS = ["Start", "Understanding", "Approaches", "World", "Delivery"] as const;
const BANNER = "Fixture replay — dev data, not a real run";

/** S-01 starts only with text in the task box. */
const fillStart = (page: Page) => page.getByLabel("Describe your task").fill("Triage my inbox");

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
      if (screen === "Start") await fillStart(page);
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
      if (screen === "Start") await fillStart(page);
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

// UX-1: a client with latency (?client_delay_ms) must not shift the layout when data arrives.
// Loading, error, empty and ready occupy one reserved box in FlowShell.
for (const viewport of [DESKTOP, MOBILE]) {
  for (const path of ["/task/t/approaches", "/world/w/delivery"]) {
    test(`PRD-18.3 UX_1: ${path} has zero layout shifts while a slow client answers at ${viewport.width}x${viewport.height}`, async ({
      page,
    }) => {
      test.setTimeout(60_000);
      await page.setViewportSize(viewport);
      await page.addInitScript(() => {
        const w = window as unknown as { __shifts: number[] };
        w.__shifts = [];
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries())
            w.__shifts.push((entry as unknown as { value: number }).value);
        }).observe({ type: "layout-shift", buffered: true });
      });
      // "commit": do not wait for the load event, which can outlast the latency. 3 s keeps the
      // loading state observable even when a parallel load delays the first poll.
      await page.goto(`${path}?client_delay_ms=3000`, { waitUntil: "commit" });
      await expect(page.getByText(/^Loading the /)).toBeVisible();
      await expect(page.getByText(/^Loading the /)).toBeHidden({ timeout: 20_000 });
      await expect(page.locator(".flow-summary")).toBeVisible();
      await page.waitForTimeout(300); // let a late shift be reported
      const shifts = await page.evaluate(
        () => (window as unknown as { __shifts: number[] }).__shifts,
      );
      expect(shifts).toEqual([]);
    });
  }
}
