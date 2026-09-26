import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";
import { stageCanvas, stageFrame } from "./support/world";

// P0-08b review finding (b): an unknown or empty ?fixture= name must not log to the console
// (Vite's SPA fallback answers a missing fixture file with index.html and status 200). Instead an
// in-app role="alert" explains the fixture could not be loaded, naming it when a name was given,
// and the stage frame still renders.

test.use({ viewport: DESKTOP });

const CASES = [
  { label: "unknown", query: "?fixture=no-such-fixture", name: "no-such-fixture" },
  { label: "empty", query: "?fixture=", name: null },
] as const;

for (const { label, query, name } of CASES) {
  test(`FR_WLD_04 P0-08b fixture mode: an ${label} ?fixture= shows an in-app alert and logs nothing`, async ({
    page,
  }) => {
    const messages: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" || msg.type() === "warning") {
        messages.push(`[${msg.type()}] ${msg.text()}`);
      }
    });
    page.on("pageerror", (err) => messages.push(`[pageerror] ${err.message}`));

    await page.goto(`/${query}`);
    await expect(stageFrame(page)).toBeVisible();
    await expect(stageCanvas(page)).toBeVisible();

    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/could not be loaded/i);
    if (name !== null) await expect(alert).toContainText(name);

    await page.waitForTimeout(500);
    expect(messages, messages.join("\n")).toEqual([]);
  });
}

test("FR_WLD_04 P0-08b fixture mode: a valid fixture shows no alert", async ({ page }) => {
  await page.goto("/?fixture=village-basic&seq=20");
  await expect(stageCanvas(page)).toBeVisible();
  await expect.poll(async () => stageFrame(page).getAttribute("data-seq")).toBe("20");
  await expect(page.getByRole("alert")).toHaveCount(0);
});
