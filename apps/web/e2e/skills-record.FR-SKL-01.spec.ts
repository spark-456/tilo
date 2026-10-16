import { expect, test } from "@playwright/test";

test.use({
  launchOptions: {
    args: [
      "--use-fake-ui-for-media-stream",
      "--auto-select-desktop-capture-source=Entire screen",
      "--allow-http-screen-capture",
    ],
  },
});

test("test_FR_SKL_01_S3_record_preview_use_shows_served_steps", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/skills-record-harness.html", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "+ Teach Tilo a skill" }).click();
  await page.getByRole("button", { name: "Start recording" }).click();
  await expect(page.getByRole("button", { name: "Stop recording" })).toBeVisible();
  await page.waitForTimeout(3_000);
  await page.getByRole("button", { name: "Stop recording" }).click();
  await expect(page.getByLabel("Recording preview")).toBeVisible();
  await expect(page.locator("body")).toHaveAttribute("data-captures", "0");
  await page.getByRole("button", { name: "Use this recording" }).click();
  await expect(page.locator("body")).toHaveAttribute("data-captures", "1");
  await expect(page.getByText("Open the page and review the request.")).toBeVisible();
});
