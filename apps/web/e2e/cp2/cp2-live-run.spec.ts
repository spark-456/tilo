// @cp2 CP2 end-to-end walk on the real dev API (services/api `just dev-api`: fake Director, fake
// unit runner, recording mock adapters, in-memory store; no credentials, no live-mode variable, no
// network call). Run with `just e2e-cp2` (TILO_CP2=1, project "cp2"); CI does not start the API, so
// the unit tests with a mocked fetch (src/api/http.test.ts) cover the client there.
//
// Type a task -> answers -> approach and cap -> the stage and the HUD follow the live run -> the
// Needs-you gate appears -> approve on S-07 -> world.completed -> delivery. Every claim below is
// read from what the API recorded (HR-1): no step waits on a timer.
import { type Page, expect, test } from "@playwright/test";
import { startRun, watchConsole } from "../support/cp2";
import { readShifts, resetShifts, watchShifts } from "../support/shifts";
import { DESKTOP } from "../support/viewports";

/** How many distinct colours the stage canvas shows (sampled): a bare iso grid shows two. */
const drawnColours = (page: Page) =>
  page.evaluate(() => {
    const canvas = document.querySelector<HTMLCanvasElement>('[data-testid="stage-frame"] canvas');
    if (!canvas) return 0;
    const copy = document.createElement("canvas");
    copy.width = canvas.width;
    copy.height = canvas.height;
    const g = copy.getContext("2d");
    if (!g) return 0;
    g.drawImage(canvas, 0, 0);
    const px = g.getImageData(0, 0, copy.width, copy.height).data;
    const seen = new Set<number>();
    for (let i = 0; i < px.length; i += 4 * 61) {
      seen.add(((px[i] ?? 0) << 16) | ((px[i + 1] ?? 0) << 8) | (px[i + 2] ?? 0));
    }
    return seen.size;
  });

type Layout = {
  semantic: {
    levels: { id: string; districts: { id: string; buildings: { id: string }[] }[] }[];
    islands: { id: string }[];
    gates: { id: string }[];
  };
  geometry: unknown;
};

/** TEST ONLY: the dev API sends `geometry: null` (the solver is not wired into the API yet), so the
 * live stage has nothing to place. This stands in for the solver at the network edge, to prove the
 * web draws a live run's layout and events through the existing pipeline. Nothing in apps/web does it. */
function withTestGeometry(layout: Layout): Layout {
  const districts = layout.semantic.levels.flatMap((l) => l.districts);
  return {
    ...layout,
    geometry: {
      solver_version: "1.0.0",
      levels: layout.semantic.levels.map((l, index) => ({
        id: l.id,
        index,
        plate: { x: 0, y: 0, w: 20, d: 14 },
      })),
      districts: districts.map((d, i) => ({
        id: d.id,
        plot: { x: 1 + i * 6, y: 1, w: 5, d: 10 },
        tint: `district.${(i % 6) + 1}`,
      })),
      buildings: districts.flatMap((d, i) =>
        d.buildings.map((b, j) => ({
          id: b.id,
          footprint: { x: 2 + i * 6, y: 2 + j * 3, w: 2, d: 2 },
          floors: 1,
        })),
      ),
      islands: layout.semantic.islands.map((n, i) => ({
        id: n.id,
        level: "L1",
        plot: { x: 16, y: 1 + i * 4, w: 3, d: 3 },
      })),
      roads: [],
      bridges: [],
      gates: layout.semantic.gates.map((g, i) => ({ id: g.id, cell: { x: 12, y: 2 + i } })),
    },
  };
}

test.describe("@cp2 CP2 live run on the real dev API", () => {
  test("FR-WLD-05 CP2: task -> answers -> approach -> live world -> gate -> approve -> delivery, with no console error and no layout shift", async ({
    page,
  }) => {
    test.setTimeout(90_000);
    await page.setViewportSize(DESKTOP);
    const problems = watchConsole(page);
    await watchShifts(page);

    const world = await startRun(page);

    // S-04 World: the layout loads (honest note until it does) and the events arrive
    const stage = page.getByTestId("stage-frame");
    await expect(stage).toHaveAttribute("data-stage-ready", "true");
    // The API's solver (CL-INT-6) attaches the map, so the note ends as soon as the layout is read.
    await expect(page.getByTestId("live-world-note")).toHaveCount(0, { timeout: 30_000 });
    await expect(stage).not.toHaveAttribute("data-seq", "0", { timeout: 30_000 });
    await expect(page.getByTestId("hud-meter")).toContainText("Working");
    await expect(page.getByRole("heading", { name: "Team" })).toBeVisible(); // the layout's agents

    // The run stops at its gate: the world's own counter says a person is needed
    await expect(page.getByTestId("needs-count")).toHaveText("1", { timeout: 30_000 });
    await resetShifts(page);
    await page.getByRole("link", { name: "Open the queue" }).click();

    // S-06 Needs you, for this run's world (not the fixture world)
    await expect(page.getByRole("heading", { level: 1, name: "Needs you" })).toBeVisible();
    expect(new URL(page.url()).searchParams.get("world")).toBe(world);
    await expect(page.getByTestId("needs-queue")).toBeVisible();
    await page.getByRole("link", { name: /^Review the gate/ }).click();

    // S-07 Gate sheet: the exact action and recipient from the recorded request
    await expect(page.getByRole("heading", { level: 1, name: "Approval gate" })).toBeVisible();
    const sheet = page.getByTestId("gate-sheet");
    await expect(sheet).toHaveAttribute("data-gate-state", "waiting");
    await expect(sheet).toContainText("dev.recipient@example.com");
    await expect(sheet).not.toContainText("undefined");
    expect(await readShifts(page)).toEqual([]);

    // Approve: the answer is sent, then the sheet follows the recorded approval.resolved
    await sheet.getByRole("radio", { name: "Approve" }).check();
    await sheet.getByRole("button", { name: "Approve" }).click();
    await expect(sheet).toHaveAttribute("data-gate-state", "decided", { timeout: 30_000 });
    await expect(sheet).toHaveAttribute("data-opened-by", "person");

    // world.completed is on record: only then is the delivery asked for (no 409 on the console)
    await page.getByRole("link", { name: "World", exact: true }).first().click();
    await expect(page).toHaveURL(new RegExp(`/world/${world}/stage$`));
    await expect(page.getByTestId("hud-meter")).toContainText("Done", { timeout: 30_000 });
    await page.getByRole("button", { name: "View delivery" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Delivery" })).toBeVisible();
    await expect(page.getByTestId("delivery")).toContainText("Finished: 1 deliverable is ready", {
      timeout: 30_000,
    });

    expect(problems).toEqual([]);
  });

  test("FR-WLD-05 CP2: a layout with solver geometry is drawn on the stage as the live events arrive", async ({
    page,
  }) => {
    test.setTimeout(90_000);
    await page.setViewportSize(DESKTOP);
    const problems = watchConsole(page);
    await page.route("**/worlds/*/layout", async (route) => {
      const response = await route.fetch();
      await route.fulfill({
        response,
        json: withTestGeometry((await response.json()) as Layout),
      });
    });

    await startRun(page);
    const stage = page.getByTestId("stage-frame");
    await expect(stage).toHaveAttribute("data-stage-ready", "true");
    await expect(page.getByTestId("live-world-note")).toHaveCount(0, { timeout: 30_000 }); // a map exists
    await expect(page.getByTestId("needs-count")).toHaveText("1", { timeout: 30_000 });
    // The run's events have drawn its districts and buildings: more than the bare iso grid.
    await expect.poll(() => drawnColours(page)).toBeGreaterThan(3);
    const seq = Number(await stage.getAttribute("data-seq"));
    expect(seq).toBeGreaterThan(1);
    expect(problems).toEqual([]);
  });

  test("CP2 #258: a bare /needs-you before any run says 'No run yet', with no request and no console error", async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP);
    const problems = watchConsole(page);
    const asked: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes("/worlds/")) asked.push(new URL(req.url()).pathname);
    });
    await page.goto("/needs-you");
    await expect(page.getByRole("heading", { level: 1, name: "Needs you" })).toBeVisible();
    await expect(page.getByTestId("no-run")).toContainText("No run yet");
    expect(asked).toEqual([]);
    expect(problems).toEqual([]);
  });

  // The Library says the same; its shell still fills the right rail from the fixture world (App.tsx),
  // which is #253's to change, so only its words are checked here.
  test("CP2 #258: a bare /library before any run says 'No run yet'", async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto("/library");
    await expect(page.getByRole("heading", { level: 1, name: "Library" })).toBeVisible();
    await expect(page.getByTestId("no-run")).toContainText("No run yet");
  });

  test("CP2 #258: an unknown world says Not found and its events are asked for once, not on every poll", async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP);
    const events: string[] = [];
    page.on("request", (req) => {
      if (req.url().endsWith("/worlds/bogus/events")) events.push(req.url());
    });
    await page.goto("/world/bogus/stage");
    await expect(page.getByTestId("not-found")).toBeVisible();
    await page.waitForTimeout(3_500); // longer than three poll gaps: a repeating poll would show here
    expect(events).toHaveLength(1);
  });
});
