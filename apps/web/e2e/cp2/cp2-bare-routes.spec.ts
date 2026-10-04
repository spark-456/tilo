// @cp2 #264 / #258: with a live API and no run started in this tab, every screen that reads one run
// from a bare address says "No run yet" and asks the API about no world, in particular never the
// fixture world (w_village_basic), which the real API answers with 404 or 403 on every poll. Run
// with `just e2e-cp2` (project "cp2", the real dev API through the HTTP-mode Vite server).
import { type Page, expect, test } from "@playwright/test";
import { DESKTOP } from "../support/viewports";

const BARE = [
  "/needs-you",
  "/needs-you/gate",
  "/needs-you/consent",
  "/meeting",
  "/library",
  "/library/artifacts",
  "/worlds",
  "/autonomy",
  "/channels",
  "/mail",
  "/team",
  "/connections",
  "/estimate",
];

/** Console errors and warnings and uncaught page errors, until the test ends. */
function watchConsole(page: Page): string[] {
  const problems: string[] = [];
  page.on("pageerror", (err) => problems.push(err.message));
  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warning") problems.push(msg.text());
  });
  return problems;
}

test.describe("@cp2 bare routes with a live API and no run", () => {
  test("FR-WLD-05 CP2 (#258): each bare route says No run yet and never asks about w_village_basic", async ({
    page,
  }) => {
    test.setTimeout(90_000);
    await page.setViewportSize(DESKTOP);
    const problems = watchConsole(page);
    const worldRequests: string[] = [];
    page.on("request", (req) => {
      if (/\/worlds\//.test(new URL(req.url()).pathname)) worldRequests.push(req.url());
    });

    for (const path of BARE) {
      await page.goto(path);
      await expect(page.getByTestId("fixture-replay-banner")).toHaveCount(0); // a real client
      // S-14 lists worlds: with none it is its own empty state, the other screens say "No run yet"
      if (path === "/worlds") await expect(page.getByTestId("worlds-empty"), path).toBeVisible();
      else await expect(page.getByTestId("no-run"), path).toContainText("No run yet");
      await expect(page.getByTestId("not-found"), path).toHaveCount(0);
    }
    await page.waitForTimeout(1500); // two poll periods: a stray poll would show up now
    expect(worldRequests).toEqual([]);
    expect(problems).toEqual([]);
  });
});
