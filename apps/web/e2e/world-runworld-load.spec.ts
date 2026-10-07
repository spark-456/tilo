import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";
import { stageFrame } from "./support/world";

// NFR-01 loads runWorld.ts (the world's choreography and renderer) by dynamic import. When that chunk
// does not arrive the world says so in words, with no unhandled rejection, and "Try again" reloads
// the page: a browser keeps a failed dynamic import for the life of the page, so importing again
// would never reach the network.

test.use({ viewport: DESKTOP });

const RUN_WORLD_CHUNK = /\/world\/runWorld\.ts/; // the dev server's name; the build's is runWorld-<hash>.js

test("NFR-01 a runWorld chunk that fails to load on /world/:id/stage says so, and Try again reloads and draws it", async ({
  page,
}) => {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`[pageerror] ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/i.test(m.text())) {
      problems.push(`[console] ${m.text()}`);
    }
  });
  let blocked = 0;
  await page.route(RUN_WORLD_CHUNK, (route) => {
    blocked += 1;
    return route.abort();
  });
  await page.goto("/world/w_village_basic/stage?speed=1000");

  const note = page.getByTestId("live-world-note");
  await expect(note).toBeVisible();
  await expect(note).toContainText("couldn't be drawn");
  await expect(note).toHaveAttribute("role", "alert");
  expect(blocked).toBeGreaterThan(0);

  await page.unroute(RUN_WORLD_CHUNK); // the connection is back
  await Promise.all([
    page.waitForEvent("load"),
    note.getByRole("button", { name: "Try again" }).click(),
  ]);
  await expect.poll(async () => stageFrame(page).getAttribute("data-seq")).toBe("44");
  await expect(page.getByTestId("live-world-note")).toHaveCount(0);
  expect(problems).toEqual([]);
});
