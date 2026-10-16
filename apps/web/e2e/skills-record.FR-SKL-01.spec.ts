import { expect, test } from "@playwright/test";
type RecorderModule = typeof import("../src/park/pages/Skills/recorder");

test.use({
  launchOptions: {
    args: [
      "--use-fake-ui-for-media-stream",
      "--auto-select-desktop-capture-source=Entire screen",
      "--allow-http-screen-capture",
    ],
  },
});

test("test_FR_SKL_01_S3_records_three_seconds_locally_before_any_upload", async ({ page }) => {
  test.setTimeout(60_000);
  let uploads = 0;
  page.on("request", (request) => {
    if (request.url().includes("/v1/skills/captures/media")) uploads++;
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.evaluate(() => {
    const button = document.createElement("button");
    button.textContent = "Capture sample";
    button.onclick = async () => {
      const path = "/src/park/pages/Skills/recorder.ts";
      const { recordScreen } = (await import(/* @vite-ignore */ path)) as RecorderModule;
      const recording = await recordScreen(false, (file) => {
        document.body.dataset.recorded = file?.name ?? "empty";
      });
      window.setTimeout(() => recording.stop(), 3000);
    };
    document.body.append(button);
  });
  await page.getByRole("button", { name: "Capture sample" }).click();
  await expect(page.locator("body")).toHaveAttribute("data-recorded", "screen-recording.webm", {
    timeout: 10_000,
  });
  expect(uploads).toBe(0);
});
