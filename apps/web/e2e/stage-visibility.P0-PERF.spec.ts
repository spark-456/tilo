import { expect, test } from "@playwright/test";
import { CAMERA_PAN_MS } from "../src/stage/camera";

test.setTimeout(90_000);

async function gotoRecordedStage(page: import("@playwright/test").Page) {
  await page.goto("/world/w_village_basic/stage?fixture=village-basic&seq=44");
  await expect(page.getByTestId("stage-frame")).toHaveAttribute("data-stage-ready", "true", {
    timeout: 45_000,
  });
}

test("P0_PERF_hidden_stage_holds_its_canvas_until_the_tab_returns", async ({ page }) => {
  await gotoRecordedStage(page);
  const stage = page.getByTestId("stage-frame");
  const before = Number(await stage.getAttribute("data-camera-x"));
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    document.dispatchEvent(new Event("visibilitychange"));
    document
      .querySelector('[data-testid="stage-frame"]')
      ?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
  });
  await page.waitForTimeout(CAMERA_PAN_MS + 100);
  expect(Number(await stage.getAttribute("data-camera-x"))).toBe(before);

  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(async () => Number(await stage.getAttribute("data-camera-x"))).not.toBe(before);
});

test("P0_PERF_offscreen_stage_holds_its_canvas_until_it_is_visible", async ({ page }) => {
  await gotoRecordedStage(page);
  const stage = page.getByTestId("stage-frame");
  const before = Number(await stage.getAttribute("data-camera-x"));
  await stage.evaluate((element) => {
    element.style.transform = "translateY(200vh)";
  });
  await page.waitForTimeout(100); // let the viewport observer deliver the exit
  await stage.dispatchEvent("keydown", { key: "ArrowRight", bubbles: true });
  await page.waitForTimeout(CAMERA_PAN_MS + 100);
  expect(Number(await stage.getAttribute("data-camera-x"))).toBe(before);
  await stage.evaluate((element) => {
    element.style.transform = "";
  });
  await expect.poll(async () => Number(await stage.getAttribute("data-camera-x"))).not.toBe(before);
});

test("P0_PERF_replay_dock_keeps_its_track_still_when_the_run_loads", async ({ page }) => {
  await page.addInitScript(() => {
    (window as typeof window & { __dockShifts: number[] }).__dockShifts = [];
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const shift = entry as PerformanceEntry & {
          hadRecentInput: boolean;
          value: number;
          sources?: { node?: Node }[];
        };
        if (shift.hadRecentInput) continue;
        if (
          shift.sources?.some((source) =>
            (source.node as Element | undefined)?.closest?.("[data-testid='replay-scrubber']"),
          )
        )
          (window as typeof window & { __dockShifts: number[] }).__dockShifts.push(shift.value);
      }
    }).observe({ type: "layout-shift", buffered: true });
  });
  await gotoRecordedStage(page);
  await page.waitForTimeout(2000);
  expect(
    await page.evaluate(() => (window as typeof window & { __dockShifts: number[] }).__dockShifts),
  ).toEqual([]);
});
