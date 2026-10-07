import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";
import { BARE_STAGE_PATH, fixtureUrl, stageCanvas, stageFrame } from "./support/world";

// NFR-01 code-splits Pixi off the landing route. A chunk that does not arrive (offline, a deploy that
// replaced the hash, a blocker) must not leave an unexplained blank stage or an unhandled rejection:
// on a world the stage says so in words and "Try again" loads it; the bare landing grid just stays
// empty.

test.use({ viewport: DESKTOP });

const PIXI_CHUNK = /\/pixi(__|\.)js/; // the dev server pre-bundles it as pixi__js.js

/** Page errors, and console errors other than the browser's own line for the aborted request. */
function watch(page: import("@playwright/test").Page) {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`[pageerror] ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/i.test(m.text())) {
      problems.push(`[console] ${m.text()}`);
    }
  });
  return problems;
}

test("NFR-01 a Pixi chunk that fails to load on a world says so, and Try again draws it", async ({
  page,
}) => {
  const problems = watch(page);
  let blocked = 0;
  await page.route(PIXI_CHUNK, (route) => {
    // The page's own entry script is not the chunk: only the dynamically imported one is aborted.
    if (route.request().resourceType() !== "script" || route.request().url().includes("/src/")) {
      return route.continue();
    }
    blocked += 1;
    return route.abort();
  });
  await page.goto(fixtureUrl("village-basic", { seq: 44 }));

  const alert = page.getByTestId("stage-load-failed");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("couldn't be drawn");
  await expect(stageCanvas(page)).toHaveCount(0);
  expect(blocked).toBeGreaterThan(0);

  await page.unroute(PIXI_CHUNK); // the connection is back
  await alert.getByRole("button", { name: "Try again" }).click();
  await expect(stageFrame(page)).toHaveAttribute("data-stage-ready", "true");
  await expect(alert).toHaveCount(0);
  expect(problems).toEqual([]);
});

test("NFR-01 a Pixi chunk that fails to load on the bare stage grid stays quiet", async ({
  page,
}) => {
  const problems = watch(page);
  await page.route(PIXI_CHUNK, (route) =>
    route.request().resourceType() === "script" && !route.request().url().includes("/src/")
      ? route.abort()
      : route.continue(),
  );
  await page.goto(BARE_STAGE_PATH);
  await expect(stageFrame(page)).toBeVisible();
  await page.waitForTimeout(2500); // past the grid's 1.5 s wait
  await expect(page.getByTestId("stage-load-failed")).toHaveCount(0);
  expect(problems).toEqual([]);
});
