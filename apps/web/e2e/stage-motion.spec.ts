import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP });

async function cameraTransitionMs(page: import("@playwright/test").Page): Promise<number> {
  return page.getByTestId("stage-frame").evaluate((el) => {
    const camera = el.querySelector<HTMLElement>('[data-testid="camera"]') ?? el;
    return Number.parseFloat(getComputedStyle(camera).transitionDuration || "0") * 1000;
  });
}

test("PRD-18.2 stage motion: camera pan/zoom uses the 320ms duration from the design system", async ({
  page,
}) => {
  await page.goto("/");
  const ms = await cameraTransitionMs(page);
  expect(ms).toBeGreaterThanOrEqual(300);
  expect(ms).toBeLessThanOrEqual(340);
});

test("PRD-9.7 stage: keyboard arrow keys pan the camera", async ({ page }) => {
  await page.goto("/");
  const stage = page.getByTestId("stage-frame");
  await stage.focus();

  const transformBefore = await stage.evaluate((el) => {
    const camera = el.querySelector<HTMLElement>('[data-testid="camera"]') ?? el;
    return getComputedStyle(camera).transform;
  });

  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(400); // > the 320ms camera duration

  const transformAfter = await stage.evaluate((el) => {
    const camera = el.querySelector<HTMLElement>('[data-testid="camera"]') ?? el;
    return getComputedStyle(camera).transform;
  });

  expect(transformAfter, "ArrowRight did not pan the camera (PRD 9.7 keyboard pan)").not.toBe(
    transformBefore,
  );
});

test.describe("reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("PRD-9.7/18.2 stage motion: reduced motion makes the camera move instantly, not in 320ms", async ({
    page,
  }) => {
    await page.goto("/");
    const ms = await cameraTransitionMs(page);
    expect(ms).toBe(0);
  });
});
