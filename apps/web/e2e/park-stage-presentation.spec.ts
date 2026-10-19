import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1920, height: 1080 }, reducedMotion: "reduce" });

test("FR_WLD_12 S-25 Park presentation stays readable and labels its recorded demo", async ({
  page,
}, testInfo) => {
  await page.goto("/world/w_village_basic/stage?display=stage&fixture=village-basic&seq=23");
  await expect(page.getByTestId("world-stage-view")).toHaveAttribute(
    "data-stage-layout",
    "1920x1080",
  );
  await expect(page.getByTestId("stage-source-label")).toHaveText("Recorded replay");
  await expect(page.getByTestId("fixture-replay-banner")).toBeVisible();
  await expect(page.getByTestId("hud-meter")).toBeVisible();
  await expect(page.getByTestId("pause-all")).toBeVisible();
  await expect(page.getByTestId("needs-count")).toBeVisible();
  await expect(page.getByTestId("stage-rail-details")).toHaveCount(0);
  await expect(page.getByTestId("trace-list")).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Lens" })).toHaveCount(0);
  await expect(page.locator(".park-shell__nav")).toBeHidden();
  await expect(page.getByTestId("stage-frame")).toBeVisible();
  expect(
    await page
      .getByTestId("stage-source-label")
      .evaluate((el) => Number.parseFloat(getComputedStyle(el).fontSize)),
  ).toBeGreaterThanOrEqual(24);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1920);
  await testInfo.attach("Park stage 1920x1080", {
    body: await page.screenshot(),
    contentType: "image/png",
  });
  await page.getByTestId("stage-mode-exit").click();
  await expect(page.locator(".park-shell__nav")).toBeVisible();
  await expect(page.getByTestId("stage-rail-details")).toBeVisible();
});
