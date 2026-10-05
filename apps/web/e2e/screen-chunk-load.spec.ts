import { type Page, expect, test } from "@playwright/test";
import { readShifts, watchShifts } from "./support/shifts";
import { DESKTOP, MOBILE } from "./support/viewports";

// NFR-01: every screen is its own code-split chunk. One that arrives late shows a fallback in the page
// frame that is already drawn (nothing shifts when the screen lands); one that does not arrive (offline,
// a deploy that replaced the hash) says so in words and "Reload" brings it, never a blank page.

const S14_MODULE = "**/src/screens/S_14.tsx*"; // the dev server serves each screen as its own module

for (const viewport of [DESKTOP, MOBILE]) {
  const size = `${viewport.width}x${viewport.height}`;

  test(`NFR-01 ${size} a screen chunk that arrives late shows a loading line in the frame and shifts nothing`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await watchShifts(page);
    await page.route(S14_MODULE, async (route) => {
      await new Promise((r) => setTimeout(r, 1200));
      await route.continue();
    });
    await page.goto("/worlds", { waitUntil: "commit" });
    const frame = page.getByTestId("screen-page");
    await expect(page.getByTestId("screen-loading")).toBeVisible({ timeout: 20_000 }); // a cold dev server
    const before = await frame.boundingBox();
    await expect(page.getByRole("heading", { level: 1, name: "Worlds" })).toBeVisible({
      timeout: 15_000,
    });
    const after = await frame.boundingBox();
    expect(after, "the page frame does not move or resize when the screen lands").toEqual(before);
    expect(await readShifts(page)).toEqual([]);
  });

  test(`NFR-01 ${size} a screen chunk that never arrives says so, and Reload brings it`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const problems = collect(page);
    await page.route(S14_MODULE, (route) => route.abort());
    await page.goto("/worlds");
    const failed = page.getByTestId("screen-chunk-failed");
    await expect(failed).toBeVisible({ timeout: 20_000 });
    await expect(failed).toContainText("This page did not load.");
    await expect(page.getByRole("heading", { level: 1, name: "Worlds" })).toHaveCount(0);
    // The shell around it still works: the nav and the top bar are there.
    await expect(page.getByTestId("top-bar")).toBeVisible();

    await page.unroute(S14_MODULE); // the connection is back
    await failed.getByRole("button", { name: "Reload" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Worlds" })).toBeVisible();
    expect(problems).toEqual([]);
  });
}

/** Page errors and console errors other than the browser's and React's own lines for the aborted import. */
function collect(page: Page): string[] {
  const problems: string[] = [];
  page.on("pageerror", (e) => {
    // Dev React also reports an error its boundary caught; the visible message proves it was handled.
    if (!/dynamically imported module/i.test(e.message)) problems.push(`[pageerror] ${e.message}`);
  });
  page.on("console", (m) => {
    if (
      m.type() === "error" &&
      !/Failed to load resource|dynamically imported module|The above error occurred|ERR_FAILED/i.test(
        m.text(),
      )
    ) {
      problems.push(`[console] ${m.text()}`);
    }
  });
  return problems;
}
